"""Grounded narration.

Two narrators, one contract: **only numbers already in the fact store**.

* :func:`template_explanation` composes prose deterministically from facts. It
  is always available and always verifies by construction.
* :func:`llm_explanation` asks Claude to write the same thing more fluently,
  but the model is handed *only* the fact JSON - never imagery, never the raw
  arrays - and is told in the system prompt that inventing a number is a
  failure. Its output then goes through :func:`grounding.build_report`, which
  re-derives every numeral and discards the narration if any is unsupported.
"""
from __future__ import annotations

from ..config import settings
from ..processing.indices import CLASS_LABELS, INDEX_META
from ..schemas import QueryPlan, TaskType
from .context import RunContext
from .grounding import FactStore, build_report

LLM_SYSTEM = """You are the narration layer of a remote-sensing analysis system.

You are given a JSON list of FACTS that were measured by deterministic image
processing tools from real satellite pixels. You have NOT seen any imagery.

Absolute rules:
1. Every number you write MUST come from the FACTS list. Copy values exactly as
   given (you may convert a fraction to a percentage, e.g. 0.2841 -> 28.41%).
2. NEVER invent, estimate, extrapolate or round-guess any measurement,
   percentage, area, count or date.
3. If the facts do not support a claim, do not make the claim.
4. Do not add external knowledge about the place, its population, its history
   or typical conditions. Describe only what was measured.
5. Write 3-6 sentences of plain, precise scientific prose. No bullet points,
   no headings, no markdown.
6. Mention the sensor and acquisition date, and state any limitation the facts
   imply (for example high cloud fraction, or partial co-observation).

Your output is automatically checked: every numeral is matched back to the
FACTS. Any unmatched numeral causes your entire narration to be discarded."""


def _pct(v: float | None) -> str | None:
    return None if v is None else f"{v * 100:.2f}%"


def template_explanation(ctx: RunContext) -> str:
    """Deterministic narration. Every number is read straight from the store."""
    store, plan = ctx.store, ctx.plan
    s: list[str] = []

    where = ctx.place_label()
    scene = ctx.get("primary", "after", "optical", "sar", "before")
    sources = sorted({p.source for p in store.provenance})

    # --- what was retrieved ---------------------------------------------
    if scene is not None:
        head = f"The analysis used {' and '.join(sources)} over {where}"
        if plan.dates:
            head += (f" for {plan.dates[0]}" if len(plan.dates) == 1
                     else f" for {plan.dates[0]} and {plan.dates[-1]}")
        if ctx.georeferenced:
            head += f", covering {ctx.scene_area_km2:,.0f} km²"
        head += f" at {ctx.shape[1]}×{ctx.shape[0]} pixels."
        s.append(head)

    # --- task-specific body ---------------------------------------------
    task = plan.task

    if task in (TaskType.CHANGE_DETECTION, TaskType.CHANGE_VQA):
        cf = store.value("change_fraction")
        if cf is not None:
            line = f"Change Vector Analysis flags {_pct(cf)} of the co-observed area as changed"
            ca = store.value("change_area_km2")
            if ca is not None:
                line += f" ({ca:,.2f} km²)"
            thr = store.value("change_threshold")
            if thr is not None:
                line += f", using an Otsu magnitude threshold of {thr:.4f}"
            s.append(line + ".")
        moves = []
        for cls in CLASS_LABELS:
            d = store.value(f"{cls}_delta_area_km2")
            if d is not None and abs(d) > 0.01:
                moves.append((abs(d), cls, d))
        moves.sort(reverse=True)
        for _, cls, d in moves[:3]:
            rel = store.value(f"{cls}_relative_change_pct")
            verb = "grew" if d > 0 else "shrank"
            line = f"{CLASS_LABELS[cls]} {verb} by {abs(d):,.2f} km²"
            if rel is not None:
                line += f" ({rel:+.2f}% relative to the earlier date)"
            s.append(line + ".")
        for idx in ("NDVI", "MNDWI", "NBR"):
            m = store.value(f"d{idx.lower()}_mean")
            if m is None:
                continue
            b, a = store.value(f"d{idx.lower()}_before"), store.value(f"d{idx.lower()}_after")
            line = f"Mean {idx} moved by {m:+.4f}"
            if b is not None and a is not None:
                line += f", from {b:.4f} to {a:.4f}"
            s.append(line + ".")

    elif task is TaskType.OPTICAL_SAR_FUSION:
        iou = store.value("fusion_iou")
        of = store.value("fusion_optical_water_fraction")
        sf = store.value("fusion_sar_water_fraction")
        ff = store.value("fusion_water_fraction")
        if of is not None and sf is not None:
            s.append(f"The optical channel puts open water at {_pct(of)} of the scene while the "
                     f"co-registered SAR channel puts it at {_pct(sf)}.")
        if iou is not None:
            s.append(f"The two sensors agree on {iou:.3f} intersection-over-union, and the fused "
                     f"decision surface gives {_pct(ff)} water coverage.")
        rec = store.value("fusion_cloud_recovered_pixels")
        if rec is not None and rec > 0:
            km = store.value("fusion_cloud_recovered_km2")
            line = f"Radar recovered {int(rec):,} pixels of water that cloud hid from the optical sensor"
            if km:
                line += f", equivalent to {km:,.2f} km²"
            s.append(line + " - the concrete operational benefit of the cross-modal pair.")

    elif task is TaskType.TIME_SERIES:
        idx_f = store.get("ts_index")
        n = store.value("ts_observations")
        if idx_f is not None and n is not None:
            idx = str(idx_f.value)
            first, last = store.value("ts_first"), store.value("ts_last")
            net = store.value("ts_net_change")
            per_year, r2 = store.value("ts_slope_per_year"), store.value("ts_r2")
            s.append(f"The {idx} series is built from {int(n)} usable acquisitions.")
            if first is not None and last is not None:
                s.append(f"{idx} moved from {first:.4f} at the start of the series to "
                         f"{last:.4f} at the end, a net change of {net:+.4f}.")
            if per_year is not None:
                s.append(f"The ordinary-least-squares trend is {per_year:+.4f} {idx} per year "
                         f"with R² of {r2:.3f}.")

    else:
        comp = [(c, store.value(f"{c}_fraction")) for c in CLASS_LABELS]
        comp = [(c, v) for c, v in comp if v is not None and v > 0.005]
        comp.sort(key=lambda kv: -kv[1])
        if comp:
            s.append("Land-cover segmentation gives " + ", ".join(
                f"{CLASS_LABELS[c].lower()} {_pct(v)}" for c, v in comp[:4]) + ".")
        for idx in ("NDVI", "MNDWI", "NBR", "NDBI"):
            m = store.value(f"{idx.lower()}_mean")
            if m is None:
                continue
            p10, p90 = store.value(f"{idx.lower()}_p10"), store.value(f"{idx.lower()}_p90")
            line = f"Mean {idx} is {m:.4f} ({INDEX_META[idx]['reads']})"
            if p10 is not None and p90 is not None:
                line += f", with the 10th-90th percentile range spanning {p10:.4f} to {p90:.4f}"
            s.append(line + ".")
        dom = store.get("rs_dominant_class")
        if dom is not None and "out-of-domain" not in (dom.label or ""):
            acc = store.value("rs_model_test_accuracy")
            frac = store.value("rs_dominant_fraction")
            line = f"The EuroSAT-adapted classifier labels the scene mainly '{dom.value}'"
            if frac is not None:
                line += f" ({_pct(frac)} of tiles)"
            if acc is not None:
                line += f"; that model scores {_pct(acc)} on its held-out split"
            s.append(line + ".")
        swf = store.value("sar_water_fraction")
        if swf is not None:
            s.append(f"The SAR channel independently measures low-backscatter open water at "
                     f"{_pct(swf)} of the scene.")

    # --- grounding qualifiers -------------------------------------------
    cloud = store.value("cloud_or_snow_fraction")
    if cloud is not None and cloud > 0.15:
        s.append(f"Note that {_pct(cloud)} of the optical scene is cloud or snow, so the "
                 "surface measurements describe the remaining clear pixels only.")
    co = store.value("coobserved_fraction")
    if co is not None and co < 0.9:
        s.append(f"Only {_pct(co)} of the grid was observed on both dates; all change "
                 "statistics are computed over that overlap.")

    if len(s) <= 1:
        s.append("No further quantitative measurement was produced for this request.")
    return " ".join(s)


def llm_explanation(ctx: RunContext, template: str) -> tuple[str, str]:
    """Return ``(text, narrator)``. Falls back to the template on any problem."""
    if not settings.llm_available:
        return template, "template"
    try:
        import anthropic
    except ImportError:
        return template, "template"

    store: FactStore = ctx.store
    payload = {
        "question": ctx.plan.raw_query,
        "task": ctx.plan.task.value,
        "area_of_interest": ctx.plan.aoi_name,
        "dates": ctx.plan.dates,
        "data_sources": [
            {"source": p.source, "instrument": p.instrument, "platform": p.platform,
             "modality": p.modality, "acquisition_date": p.acquisition_date,
             "resolution_m": p.resolution_m, "origin": p.origin.value}
            for p in store.provenance
        ],
        "facts": store.brief(max_items=70),
        "warnings": ctx.warnings[:6],
    }
    import json

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                     timeout=float(settings.llm_timeout))
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=700,
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content":
                       "FACTS:\n" + json.dumps(payload, indent=2, default=str)
                       + "\n\nWrite the grounded narration."}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        return (text, "llm") if text else (template, "template")
    except Exception:
        return template, "template"


def narrate(ctx: RunContext, use_llm: bool | None = None):
    """Produce the final explanation plus its grounding report."""
    template = template_explanation(ctx)
    want = settings.llm_available if use_llm is None else (use_llm and settings.llm_available)
    if not want:
        return build_report(template, ctx.store, "template", fallback_text=None)
    text, narrator = llm_explanation(ctx, template)
    if narrator == "template":
        return build_report(template, ctx.store, "template", fallback_text=None)
    return build_report(text, ctx.store, "llm", fallback_text=template)


def no_data_explanation(plan: QueryPlan, reason: str, detail: dict | None = None) -> str:
    """The honest answer when the archive has nothing. Never a guess."""
    where = plan.aoi_name or "the requested area"
    text = (f"The required data is not available, so no answer can be given for {where}. "
            f"{reason}")
    probes = (detail or {}).get("probes")
    if probes:
        tried = ", ".join(f"{p['date']} ({p['coverage'] * 100:.0f}%)" for p in probes[:8])
        text += f" Acquisition dates checked and their coverage: {tried}."
    text += (" No value has been estimated or substituted - the system reports unavailability "
             "rather than producing an unsupported figure.")
    return text
