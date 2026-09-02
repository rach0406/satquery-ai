"""The Query Analysis Summary: the long result, compressed to what matters.

The full :class:`QueryResponse` is deliberately exhaustive - facts, trace,
provenance, grounding verdict. That is the right thing for an auditor and the
wrong thing for someone who just ran a query and wants to know what came back.

This module builds a short, sectioned digest from **the response that was
actually produced**. It never re-analyses anything and never introduces a
number: every value it shows is copied from a :class:`Fact` the measurement
tools published, or from the plan and provenance records. A section that has
no real content is omitted rather than filled with a placeholder, so the card
never claims a location for an image that has none.
"""
from __future__ import annotations

from ..processing.indices import CLASS_LABELS, INDEX_META
from ..schemas import (QueryPlan, SummarySection, TaskType)

#: Human-facing names for the task the planner chose.
TASK_SUMMARY_LABEL: dict[str, str] = {
    "vqa": "Visual question answering",
    "caption": "Scene description",
    "grounding": "Text-guided region grounding",
    "change_detection": "Bi-temporal change detection",
    "change_vqa": "Change-based question answering",
    "optical_sar_fusion": "Optical + SAR cross-modal analysis",
    "landcover": "Land-cover classification",
    "index_analysis": "Spectral index analysis",
    "time_series": "Index time series",
    "unsupported": "Unsupported request",
}


def _fmt(value, unit: str | None) -> str:
    """Format a fact value the same way the rest of the UI does."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    if unit == "fraction":
        return f"{value * 100:.1f}%"
    if unit == "km2":
        return f"{value:,.2f} km²"
    if unit == "pixels":
        return f"{int(value):,} px"
    if unit == "percent":
        return f"{value:+.1f}%"
    if unit in ("dates", "regions", "tiles", "scenes"):
        return f"{int(value):,} {unit}"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _section(title: str, points: list[str], kind: str = "info") -> SummarySection | None:
    """Build a section, or None when there is nothing real to show."""
    points = [p for p in points if p]
    if not points:
        return None
    return SummarySection(title=title, points=points, kind=kind)


#: Registry tool name -> the sentence a person would use for what it did.
TOOL_SUMMARY_LABEL: dict[str, str] = {
    "landcover_segmenter": "Segmented land cover from spectral indices",
    "spectral_index": "Computed spectral indices over every valid pixel",
    "rs_scene_classifier": "Ran the EuroSAT-adapted scene classifier",
    "region_grounder": "Located and outlined the requested regions",
    "change_analyzer": "Compared the two dates pixel by pixel",
    "timeseries_analyzer": "Built the index time series across dates",
    "sar_analyzer": "Analysed Sentinel-1 radar backscatter",
    "optical_sar_fusion": "Fused the optical and radar evidence",
    "vqa_resolver": "Resolved the question against the measured facts",
    "scene_captioner": "Composed the scene description from the measurements",
}


def _query_section(plan: QueryPlan) -> SummarySection | None:
    points = [TASK_SUMMARY_LABEL.get(plan.task.value, plan.task.value.replace("_", " "))]
    if plan.target_classes:
        names = [CLASS_LABELS.get(c, c).lower() for c in plan.target_classes]
        points.append("Looking for: " + ", ".join(names))
    if plan.indices:
        points.append("Indices requested: " + ", ".join(plan.indices))
    return _section("Query", points, kind="query")


def _understanding_section(plan: QueryPlan, scene_meta: dict) -> SummarySection | None:
    """"What did I ask, and how was it read?" - the first thing to check.

    Every line restates a field the parser resolved. Nothing here is inferred
    about the world: naming a phenomenon records which analysis was selected,
    not that the phenomenon occurred.
    """
    points: list[str] = []
    if plan.interpretation:
        points.append(plan.interpretation)
    if plan.event:
        points.append(f"Phenomenon recognised: {plan.event}")
    if scene_meta.get("is_upload"):
        points.append("Area: your uploaded image (its own georeferencing was used)")
    elif plan.aoi_name:
        points.append(f"Location identified: {plan.aoi_name}")
    else:
        points.append("Location: none resolved from the question")
    if plan.dates:
        points.append("Time period: " + (plan.dates[0] if len(plan.dates) == 1
                                         else f"{plan.dates[0]} to {plan.dates[-1]}"))
    # The parser's own confidence is deliberately *not* printed here: the card
    # must introduce no number that is not a measurement, and the overall
    # confidence already appears in the result-quality section.
    points.append(f"Interpreted by the {plan.parser} parser")
    return _section("What you asked", points, kind="understanding")


def _performed_section(plan: QueryPlan, store, tools_run: list[str],
                       scene_meta: dict) -> SummarySection | None:
    """"What did the system actually do?" - data in, tools run."""
    points: list[str] = []

    sources = sorted({p.source for p in getattr(store, "provenance", []) if p.source})
    if sources:
        points.append("Data used: " + "; ".join(sources[:2])
                      + (f" (+{len(sources) - 2} more)" if len(sources) > 2 else ""))
    n = store.value("scene_count")
    if n:
        points.append(f"{int(n)} scene(s) retrieved and checked for compatibility")

    ran = [TOOL_SUMMARY_LABEL[t] for t in tools_run if t in TOOL_SUMMARY_LABEL]
    for line in ran[:3]:
        points.append(line)
    if len(ran) > 3:
        points.append(f"…and {len(ran) - 3} more specialist tool(s)")
    return _section("What the system did", points, kind="performed")


def _scope_section(plan: QueryPlan) -> SummarySection | None:
    """States plainly when the question asked for something unmeasurable here."""
    if not plan.unsupported_aspect:
        return None
    return _section("Outside this sensor suite", [plan.unsupported_aspect],
                    kind="scope")


def _location_section(plan: QueryPlan, store, scene_meta: dict) -> SummarySection | None:
    """Only real location information. Silent when the image has none.

    A place name parsed from the question is *not* evidence of where an
    uploaded image was taken, so for a pixel-space scene the whole section is
    suppressed and the geographic section explains why.
    """
    if scene_meta.get("spatial_reference") == "pixel_space":
        return None

    points: list[str] = []
    located = scene_meta.get("bbox") or (not scene_meta and plan.bbox)
    if plan.aoi_name and located and not scene_meta.get("is_upload"):
        points.append(plan.aoi_name)
    box = scene_meta.get("bbox") or (plan.bbox if not scene_meta else None)
    if box and len(box) == 4:
        w, s, e, n = box
        points.append(f"Lon {w:.3f} to {e:.3f}, lat {s:.3f} to {n:.3f}")
    if plan.dates:
        points.append("Observed: " + (plan.dates[0] if len(plan.dates) == 1
                                      else " and ".join([plan.dates[0], plan.dates[-1]])))
    area = store.value("scene_area_km2")
    if area:
        points.append(f"Area covered: {area:,.0f} km²")
    return _section("Location", points, kind="location")


def _geographic_section(scene_meta: dict) -> SummarySection | None:
    """CRS / projection facts, or an honest statement that there are none."""
    if not scene_meta:
        return None
    if scene_meta.get("spatial_reference") == "georeferenced":
        points = []
        crs = (scene_meta.get("metadata") or {}).get("crs")
        if crs:
            points.append(f"CRS: {crs}")
        bbox = scene_meta.get("bbox")
        if bbox:
            points.append(f"Bounds: {bbox[0]:.4f}, {bbox[1]:.4f} to {bbox[2]:.4f}, {bbox[3]:.4f}")
        points.append("Sizes reported in km²")
        return _section("Geographic information", points, kind="geo")
    return _section("Geographic information", [
        "No geographic metadata in this image",
        "Sizes reported in pixels, not km²",
        "Image analysis is unaffected",
    ], kind="geo-none")


def _image_section(scene_meta: dict, store) -> SummarySection | None:
    if not scene_meta:
        return None
    points: list[str] = []
    w, h = scene_meta.get("width"), scene_meta.get("height")
    if w and h:
        points.append(f"{w} × {h} pixels")
    bands = scene_meta.get("bands") or []
    if bands:
        basis = ((scene_meta.get("capabilities") or {}).get("band_basis") or "")
        label = {"multispectral": "multispectral", "rgb": "RGB", "single_band": "single-band"}
        points.append(f"{len(bands)}-band {label.get(basis, '')} image".replace("  ", " ").strip())
        points.append("Bands: " + ", ".join(bands))
    meta = scene_meta.get("metadata") or {}
    if meta.get("original_size"):
        ow, oh = meta["original_size"]
        points.append(f"Downscaled for analysis from {ow} × {oh}")
    if meta.get("format"):
        points.append(f"Format: {meta['format'].upper()}")
    return _section("Image", points, kind="image")


def _findings_section(plan: QueryPlan, store) -> SummarySection | None:
    """The measured headline numbers, chosen by what the task actually is."""
    points: list[str] = []
    task = plan.task

    if task in (TaskType.CHANGE_DETECTION, TaskType.CHANGE_VQA):
        cf = store.value("change_fraction")
        if cf is not None:
            line = f"{cf * 100:.1f}% of the area changed"
            ca = store.value("change_area_km2")
            if ca is not None:
                line += f" ({ca:,.1f} km²)"
            points.append(line)
        moves = []
        for cls in CLASS_LABELS:
            d = store.value(f"{cls}_delta_area_km2")
            if d is not None and abs(d) > 0.01:
                moves.append((abs(d), cls, d))
        moves.sort(reverse=True)
        for _, cls, d in moves[:3]:
            points.append(f"{CLASS_LABELS[cls]} {'grew' if d > 0 else 'shrank'} "
                          f"by {abs(d):,.1f} km²")

    elif task is TaskType.OPTICAL_SAR_FUSION:
        for key, label in (("fusion_water_fraction", "Fused water coverage"),
                           ("fusion_iou", "Optical/SAR agreement (IoU)")):
            f = store.get(key)
            if f is not None:
                points.append(f"{label}: {_fmt(f.value, f.unit)}")
        rec = store.value("fusion_cloud_recovered_km2")
        if rec:
            points.append(f"Radar recovered {rec:,.1f} km² hidden by cloud")

    elif task is TaskType.TIME_SERIES:
        idx = store.get("ts_index")
        n = store.value("ts_observations")
        slope = store.value("ts_slope_per_year")
        if idx is not None and n is not None:
            points.append(f"{idx.value} across {int(n)} usable dates")
        if slope is not None:
            points.append(f"Trend: {slope:+.4f} per year"
                          + (f" (R² {store.value('ts_r2'):.2f})"
                             if store.value("ts_r2") is not None else ""))

    elif task is TaskType.GROUNDING:
        for cls in (plan.target_classes or ["water"]):
            n = store.value(f"grounded_{cls}_regions")
            if n is not None:
                label = CLASS_LABELS.get(cls, cls)
                line = f"{int(n)} {label.lower()} region(s) located"
                km = store.value(f"grounded_{cls}_area_km2")
                px = store.value(f"grounded_{cls}_pixels")
                if km is not None:
                    line += f", {km:,.2f} km² total"
                elif px is not None:
                    line += f", {int(px):,} px total"
                points.append(line)

    # Land-cover composition is the general fallback and also supplements the above.
    if len(points) < 4:
        comp = [(c, store.value(f"{c}_fraction")) for c in CLASS_LABELS]
        comp = [(c, v) for c, v in comp if v is not None and v > 0.02]
        comp.sort(key=lambda kv: -kv[1])
        for c, v in comp[:4 - len(points)]:
            points.append(f"{CLASS_LABELS[c]}: {v * 100:.1f}%")

    return _section("Key findings", points, kind="findings")


def _detected_section(store) -> SummarySection | None:
    """What the analysis actually found present, as plain nouns."""
    present: list[str] = []
    for cls, label in CLASS_LABELS.items():
        if cls == "unclassified":
            continue
        v = store.value(f"{cls}_fraction")
        if v is not None and v > 0.02:
            present.append(f"{label} ({v * 100:.0f}%)")
    dom = store.get("rs_dominant_class")
    if dom is not None and "out-of-domain" not in (dom.label or ""):
        present.append(f"Classifier label: {dom.value}")
    return _section("Detected features", present, kind="detected")


def _measurements_section(plan: QueryPlan, store) -> SummarySection | None:
    """Named index statistics, when the query was about an index."""
    points: list[str] = []
    for idx in (plan.indices or []) + ["NDVI", "MNDWI", "VARI"]:
        key = f"{idx.lower()}_mean"
        if store.has(key) and not any(idx in p for p in points):
            reads = INDEX_META.get(idx, {}).get("reads", "")
            points.append(f"Mean {idx}: {store.value(key):.4f}"
                          + (f" ({reads})" if reads else ""))
        if len(points) >= 3:
            break
    return _section("Measurements", points, kind="measure")


def _quality_section(response_status: str, grounding, warnings: list[str],
                     confidence: float | None) -> SummarySection | None:
    points: list[str] = []
    if grounding is not None and grounding.claims_checked:
        points.append(f"{grounding.claims_verified}/{grounding.claims_checked} "
                      "numbers traced to measurements")
    if confidence is not None:
        points.append(f"Confidence: {confidence:.2f}")
    if warnings:
        points.append(f"{len(warnings)} caveat(s) raised - see the full result")
    return _section("Result quality", points, kind="quality")


def build_summary(
    plan: QueryPlan,
    store,
    status: str,
    grounding=None,
    warnings: list[str] | None = None,
    confidence: float | None = None,
    scene_meta: dict | None = None,
    answer: str | None = None,
    tools_run: list[str] | None = None,
) -> list[SummarySection]:
    """Assemble the Query Analysis Summary from a finished response.

    Returns an ordered list of sections. Sections with nothing genuine to say
    are dropped, so the card stays short and never pads itself.
    """
    warnings = warnings or []
    scene_meta = scene_meta or {}
    tools_run = tools_run or []

    # Outcomes that produced no measurement get a short, honest card instead of
    # an empty one.
    if status in ("no_data", "needs_clarification", "unsupported", "error"):
        head = {
            "no_data": "No usable data for this request",
            "needs_clarification": "More information needed",
            "unsupported": "This request is not supported",
            "error": "The analysis could not complete",
        }[status]
        sections = [SummarySection(title="Outcome", kind="outcome", points=[head])]
        if answer:
            sections.append(SummarySection(title="What to do", kind="info",
                                           points=[answer[:220]]))
        for maybe in (_understanding_section(plan, scene_meta), _scope_section(plan)):
            if maybe:
                sections.append(maybe)
        return sections

    # Ordered so the card reads as a story: what you asked → what was done →
    # what was found → the supporting detail. Those first three are the whole
    # point of the card, so they come before anything else regardless of how
    # interesting the supporting numbers happen to be.
    candidates = [
        _understanding_section(plan, scene_meta),
        _scope_section(plan),
        _performed_section(plan, store, tools_run, scene_meta),
        _findings_section(plan, store),
        _detected_section(store),
        _measurements_section(plan, store),
        _location_section(plan, store, scene_meta),
        _image_section(scene_meta, store),
        _geographic_section(scene_meta),
        _quality_section(status, grounding, warnings, confidence),
    ]
    return [c for c in candidates if c is not None]
