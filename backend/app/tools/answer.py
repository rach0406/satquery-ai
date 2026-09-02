"""Answer synthesis: grounded VQA and scene captioning.

Neither tool looks at pixels. Both read the :class:`FactStore` that the
measurement tools filled and resolve the question against it. If the store
contains no fact that answers the question, the tools say exactly that instead
of producing a plausible sentence.
"""
from __future__ import annotations

import re

from ..agent.context import RunContext
from ..agent.grounding import fact
from ..processing.indices import CLASS_LABELS, INDEX_META
from ..schemas import ToolResult

VERSION = "1.0.0"


#: Question phrasings mapped to the fact keys that can answer them.
_CLASS_FACT_HINTS = {
    "water": ("water_fraction", "fusion_water_fraction", "sar_water_fraction",
              "water_area_km2", "fusion_water_km2"),
    "dense_vegetation": ("dense_vegetation_fraction", "dense_vegetation_area_km2", "ndvi_mean"),
    "sparse_vegetation": ("sparse_vegetation_fraction", "sparse_vegetation_area_km2"),
    "built_up": ("built_up_fraction", "built_up_area_km2", "sar_builtup_fraction"),
    "bare_soil": ("bare_soil_fraction", "bare_soil_area_km2"),
    "cloud_or_snow": ("cloud_or_snow_fraction", "cloud_or_snow_area_km2"),
}

_YES_NO = re.compile(
    r"^\s*(is|are|was|were|does|do|did|has|have|had|can|will|any)\b", re.IGNORECASE
)
_HOW_MUCH = re.compile(r"\b(how much|how many|what (is|was) the|what percentage|what share|"
                       r"how large|how big|what area)\b", re.IGNORECASE)
_DIRECTION = re.compile(r"\b(increase|increased|decrease|decreased|grow|grew|shrink|shrunk|"
                        r"expand|expanded|gain|gained|lose|lost|rise|risen|fall|fallen|"
                        r"change|changed|unchanged)\b", re.IGNORECASE)


def _fmt(value, unit: str | None) -> str:
    if isinstance(value, str):
        return value
    if unit == "fraction":
        return f"{value * 100:.2f}%"
    if unit == "km2":
        return f"{value:,.2f} km²"
    if unit == "percent":
        return f"{value:+.2f}%"
    if unit == "pixels":
        return f"{int(value):,} pixels"
    if unit in ("dates", "regions", "tiles"):
        return f"{int(value):,} {unit}"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_vqa_resolver(ctx: RunContext) -> ToolResult:
    """Resolve the question against measured facts only."""
    q = ctx.plan.raw_query
    store = ctx.store
    plan = ctx.plan

    if not store.facts:
        return ToolResult(
            tool="vqa_resolver", tool_version=VERSION, status="no_data",
            message="No measurement tool produced any fact, so there is nothing to answer from.")

    candidates: list[str] = []

    # 1. Facts implied by the classes named in the question.
    for cls in plan.target_classes:
        for key in _CLASS_FACT_HINTS.get(cls, ()):
            for suffix in ("", "_before", "_after"):
                if store.has(key + suffix):
                    candidates.append(key + suffix)

    # 2. Facts implied by a named index.
    for idx in plan.indices:
        for stat in ("mean", "median", "p90", "p10"):
            k = f"{idx.lower()}_{stat}"
            if store.has(k):
                candidates.append(k)
        for k in (f"d{idx.lower()}_mean", f"d{idx.lower()}_before", f"d{idx.lower()}_after"):
            if store.has(k):
                candidates.append(k)

    # 2b. The requested index may have been unavailable on this band stack and
    # substituted (NDVI -> VARI on a visible-only image). The substitute is a
    # real measurement of the same property, so answer from it rather than
    # claiming nothing was measured.
    if plan.indices and not candidates:
        for alt in ("VARI", "NDVI", "MNDWI", "NDWI"):
            k = f"{alt.lower()}_mean"
            if store.has(k):
                candidates.append(k)
                break

    # 3. Change questions want change facts first.
    if _DIRECTION.search(q) or plan.task.value.startswith("change"):
        for k in ("change_fraction", "change_area_km2"):
            if store.has(k):
                candidates.insert(0, k)
        for cls in plan.target_classes:
            for k in (f"{cls}_delta_area_km2", f"{cls}_relative_change_pct",
                      f"{cls}_fraction_before", f"{cls}_fraction_after"):
                if store.has(k):
                    candidates.insert(0, k)

    # 3b. Grounding questions want the located-region facts first.
    if plan.task.value == "grounding":
        for cls in (plan.target_classes or ["water"]):
            for k in (f"grounded_{cls}_regions", f"grounded_{cls}_area_km2",
                      f"grounded_{cls}_pixels"):
                if store.has(k):
                    candidates.insert(0, k)

    # 4. Cross-modal questions.
    if plan.task.value == "optical_sar_fusion":
        for k in ("fusion_water_fraction", "fusion_iou", "fusion_cloud_recovered_pixels"):
            if store.has(k):
                candidates.insert(0, k)

    # 5. Last resort: keyword-match the question against fact labels.
    if not candidates:
        words = {w for w in re.findall(r"[a-z]{4,}", q.lower())}
        scored = []
        for key, f in store.facts.items():
            hay = f"{f.label} {key}".lower()
            score = sum(1 for w in words if w in hay)
            if score:
                scored.append((score, key))
        scored.sort(reverse=True)
        candidates = [k for _, k in scored[:4]]

    # 6. An open "what is here / what is present" question is answered by the
    # measured composition, which is exactly what the segmentation produced.
    if not candidates:
        comp = [(c, store.value(f"{c}_fraction")) for c in CLASS_LABELS]
        comp = [(c, v) for c, v in comp if v is not None and v > 0.02]
        if comp:
            comp.sort(key=lambda kv: -kv[1])
            candidates = [f"{c}_fraction" for c, _ in comp[:4]]

    seen: set[str] = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    if not candidates:
        available = ", ".join(sorted({f.label for f in list(store.facts.values())[:12]}))
        return ToolResult(
            tool="vqa_resolver", tool_version=VERSION, status="no_data",
            message=(
                "The retrieved data does not contain a measurement that answers this "
                f"question. What was measured for this scene: {available}. "
                "Try asking about one of those quantities, or rephrase the question."),
        )

    primary = store.get(candidates[0])
    assert primary is not None

    # ---- compose a direct answer ----------------------------------------
    parts: list[str] = []
    if _YES_NO.match(q.strip()) and _DIRECTION.search(q):
        delta = None
        for cls in plan.target_classes:
            delta = store.value(f"{cls}_delta_area_km2")
            if delta is None:
                fb, fa = store.value(f"{cls}_fraction_before"), store.value(f"{cls}_fraction_after")
                delta = (fa - fb) if (fa is not None and fb is not None) else None
            if delta is not None:
                label = CLASS_LABELS.get(cls, cls)
                word = "increased" if delta > 0 else ("decreased" if delta < 0 else "stayed level")
                rel = store.value(f"{cls}_relative_change_pct")
                sentence = f"Yes — {label.lower()} {word}"
                if store.has(f"{cls}_delta_area_km2"):
                    sentence += f" by {abs(delta):,.2f} km²"
                if rel is not None:
                    sentence += f" ({rel:+.2f}% relative to the earlier date)"
                parts.append(sentence + ".")
                break
        if not parts:
            cf = store.value("change_fraction")
            if cf is not None:
                parts.append(
                    f"Measured change affects {cf * 100:.2f}% of the co-observed area.")
    elif _HOW_MUCH.search(q):
        parts.append(f"{primary.label}: {_fmt(primary.value, primary.unit)}.")
    else:
        parts.append(f"{primary.label}: {_fmt(primary.value, primary.unit)}.")

    for key in candidates[1:4]:
        f = store.get(key)
        if f is None or f.key == primary.key:
            continue
        parts.append(f"{f.label}: {_fmt(f.value, f.unit)}.")

    answer = " ".join(parts)

    facts = [fact(
        key="vqa_primary_fact", label="Fact used to answer the question",
        value=primary.key,
        method=f"selected from {len(store.facts)} measured facts by intent matching",
        tool="vqa_resolver", source=primary.source)]

    return ToolResult(
        tool="vqa_resolver", tool_version=VERSION, status="ok",
        message=f"Answered from fact '{primary.key}' (+{len(candidates) - 1} supporting).",
        facts=facts, answer=answer, confidence=primary.confidence or 0.85,
        parameters={"candidate_facts": candidates[:6], "primary_fact": primary.key},
    )


def run_scene_captioner(ctx: RunContext) -> ToolResult:
    """Describe the scene using only measured composition and statistics."""
    store = ctx.store
    scene = ctx.get("primary", "after", "optical", "sar", "before")
    if scene is None:
        return ToolResult(tool="scene_captioner", tool_version=VERSION, status="skipped",
                          message="No scene is loaded.")

    fractions: list[tuple[str, float]] = []
    for cls in CLASS_LABELS:
        v = store.value(f"{cls}_fraction")
        if v is not None and v > 0.005:
            fractions.append((cls, v))
    fractions.sort(key=lambda kv: -kv[1])

    bits: list[str] = []
    where = ctx.place_label()
    when = f" on {scene.date}" if scene.date else ""
    area = f" covering {ctx.scene_area_km2:,.0f} km²" if ctx.georeferenced else ""
    bits.append(
        f"{scene.provenance.source} imaged {where}{when}{area} at "
        f"{ctx.shape[1]}×{ctx.shape[0]} pixels.")

    if fractions:
        top = fractions[:3]
        desc = ", ".join(f"{CLASS_LABELS[c].lower()} {v * 100:.1f}%" for c, v in top)
        bits.append(f"The scene is dominated by {desc}.")
        rest = fractions[3:]
        if rest:
            bits.append("Also present: " + ", ".join(
                f"{CLASS_LABELS[c].lower()} {v * 100:.1f}%" for c, v in rest) + ".")

    dom = store.get("rs_dominant_class")
    if dom is not None and "out-of-domain" not in (dom.label or ""):
        conf = store.value("rs_mean_confidence")
        tiles = store.value("rs_tiles")
        frac = store.value("rs_dominant_fraction")
        s = (f"The EuroSAT-adapted classifier labels the scene predominantly "
             f"'{dom.value}'")
        if frac is not None:
            s += f" ({frac * 100:.1f}% of {int(tiles or 0)} tiles)"
        if conf is not None:
            s += f", mean confidence {conf:.2f}"
        bits.append(s + ".")

    for idx in ("NDVI", "MNDWI", "NBR", "NDBI"):
        m = store.value(f"{idx.lower()}_mean")
        if m is None:
            continue
        p10, p90 = store.value(f"{idx.lower()}_p10"), store.value(f"{idx.lower()}_p90")
        s = f"Mean {idx} is {m:.3f} ({INDEX_META[idx]['reads']})"
        if p10 is not None and p90 is not None:
            s += f", with 80% of pixels between {p10:.3f} and {p90:.3f}"
        bits.append(s + ".")

    swf = store.value("sar_water_fraction")
    if swf is not None:
        bits.append(
            f"The co-registered SAR channel puts low-backscatter (open-water) surfaces at "
            f"{swf * 100:.2f}% of the scene.")

    cf = store.value("change_fraction")
    if cf is not None:
        bits.append(f"Comparing the two dates, {cf * 100:.2f}% of the co-observed area changed.")

    cloud = store.value("cloud_or_snow_fraction")
    if cloud is not None and cloud > 0.2:
        bits.append(
            f"Note that {cloud * 100:.1f}% of the scene is cloud or snow, which limits how "
            "much of the surface the optical sensor could measure.")

    if len(bits) <= 1:
        return ToolResult(
            tool="scene_captioner", tool_version=VERSION, status="no_data",
            message=("No composition or index measurement is available for this scene, so no "
                     "grounded description can be produced."))

    caption = " ".join(bits)
    return ToolResult(
        tool="scene_captioner", tool_version=VERSION, status="ok",
        message=f"Composed a description from {len(store.facts)} measured facts.",
        answer=caption, confidence=0.86,
        facts=[fact(key="caption_fact_count", label="Facts used in the description",
                    value=len(store.facts), unit=None,
                    method="count of measured facts available to the captioner",
                    tool="scene_captioner")],
    )
