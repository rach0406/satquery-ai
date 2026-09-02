"""Single-image optical specialists: indices, segmentation, classification, grounding."""
from __future__ import annotations

import numpy as np

from ..agent.context import RunContext
from ..agent.grounding import fact
from ..ml import classifier
from ..processing import indices as IX
from ..processing import regions as RG
from ..schemas import ToolResult
from ..utils import render

VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Spectral index engine
# --------------------------------------------------------------------------
def run_spectral_index(ctx: RunContext, indices: list[str] | None = None,
                       histogram_bins: int = 40) -> ToolResult:
    scene = ctx.get("primary", "after", "optical", "before")
    if scene is None:
        return ToolResult(tool="spectral_index", tool_version=VERSION, status="skipped",
                          message="No optical scene is loaded.")

    wanted = [i.upper() for i in (indices or ctx.plan.indices or ["NDVI", "MNDWI"])]
    usable = IX.available_indices(scene.bands)
    missing = [i for i in wanted if i not in usable]
    wanted = [i for i in wanted if i in usable]
    substituted = False

    if not wanted:
        # Nothing requested is computable. Rather than returning empty-handed,
        # compute what this band stack *can* support and say plainly that the
        # requested index was substituted - a visible-only image can still
        # answer a greenness question through VARI, just less well.
        if not usable:
            return ToolResult(
                tool="spectral_index", tool_version=VERSION, status="no_data",
                message=(
                    f"None of the requested indices {missing} can be computed from this "
                    f"scene, and neither can any other: it provides only bands "
                    f"{sorted(scene.bands)}."
                ),
            )
        wanted = usable[:2]
        substituted = True
        ctx.warn(
            f"{', '.join(missing)} need near-infrared or shortwave-infrared bands, which "
            f"this image does not have. {', '.join(wanted)} was computed instead from the "
            "visible bands. It answers a similar question with less physical grounding, so "
            "treat the value as indicative."
        )

    facts, arts = [], []
    for name in wanted:
        arr = IX.compute_index(name, scene.bands)
        st = IX.index_stats(arr, scene.valid, name, bins=histogram_bins)
        ctx.cache[f"index:{name}:{scene.role}"] = arr
        ctx.cache[f"indexstats:{name}:{scene.role}"] = st

        meta = IX.INDEX_META[name]
        method = f"{meta['name']} = normalised difference over {IX.INDEX_REQUIREMENTS[name]}"
        src = scene.provenance.source
        for stat, val, lbl in (
            ("mean", st.mean, "mean"), ("median", st.median, "median"),
            ("std", st.std, "standard deviation"), ("min", st.minimum, "minimum"),
            ("max", st.maximum, "maximum"), ("p10", st.p10, "10th percentile"),
            ("p90", st.p90, "90th percentile"),
        ):
            facts.append(fact(
                key=f"{name.lower()}_{stat}", label=f"{name} {lbl}", value=val,
                method=f"{method}; {lbl} over {st.valid_pixels} valid pixels",
                tool="spectral_index", source=src, sample_size=st.valid_pixels,
            ))
        facts.append(fact(
            key=f"{name.lower()}_valid_pixels", label=f"{name} valid pixel count",
            value=st.valid_pixels, unit="pixels",
            method="count of finite index values inside the observed mask",
            tool="spectral_index", source=src,
        ))

        palette = {"NDVI": "rdylgn", "VARI": "rdylgn", "NBR": "rdylgn",
                   "NDWI": "blues", "MNDWI": "blues",
                   "NDBI": "magma", "BSI": "magma"}.get(name, "rdylgn")
        overlay = IX.colorise_index(arr, scene.valid, -1.0, 1.0, palette)
        arts.append(render.image_artifact(
            overlay, f"{name} - {scene.label}", scene.bbox,
            description=f"{meta['name']} ({meta['reads']}), range {meta['range']}. {meta['reference']}.",
            provenance=scene.provenance, colormap=palette,
            legend=render.ramp_legend(-1.0, 1.0, palette), prefix=f"{name.lower()}",
        ))
        arts.append(render.histogram_chart(
            f"{name} distribution - {scene.label}", st.histogram, st.bin_edges,
            xlabel=f"{name} value", color="#3987e5",
            marker_lines=[
                {"x": st.mean, "label": f"mean {st.mean:.3f}", "color": "#d95926"},
                {"x": st.median, "label": f"median {st.median:.3f}", "color": "#199e70"},
            ],
        ))

    rows = []
    for name in wanted:
        st = ctx.cache[f"indexstats:{name}:{scene.role}"]
        rows.append({
            "index": name, "meaning": IX.INDEX_META[name]["reads"],
            "mean": round(st.mean, 4), "median": round(st.median, 4),
            "std": round(st.std, 4), "p10": round(st.p10, 4), "p90": round(st.p90, 4),
            "min": round(st.minimum, 4), "max": round(st.maximum, 4),
            "valid_pixels": st.valid_pixels,
        })
    arts.append(render.table_artifact(
        "Spectral index statistics",
        [{"key": "index", "label": "Index"}, {"key": "meaning", "label": "Measures"},
         {"key": "mean", "label": "Mean"}, {"key": "median", "label": "Median"},
         {"key": "std", "label": "Std dev"}, {"key": "p10", "label": "P10"},
         {"key": "p90", "label": "P90"}, {"key": "min", "label": "Min"},
         {"key": "max", "label": "Max"}, {"key": "valid_pixels", "label": "Valid px"}],
        rows,
        description=f"Computed from {scene.provenance.source} acquired {scene.date}.",
    ))

    msg = f"Computed {', '.join(wanted)} over {ctx.shape[1]}x{ctx.shape[0]} pixels."
    if missing and not substituted:
        msg += f" Skipped {missing} - required bands unavailable from this sensor."
        ctx.warn(f"Indices {missing} unavailable: sensor stack lacks the required bands.")
    elif substituted:
        msg += f" Requested {missing} needs NIR/SWIR, which this image lacks."
    return ToolResult(
        tool="spectral_index", tool_version=VERSION, status="ok", message=msg,
        facts=facts, artifacts=arts, provenance=[scene.provenance],
        confidence=0.70 if substituted else 0.95,
        parameters={"indices": wanted, "histogram_bins": histogram_bins,
                    "substituted_for": missing if substituted else []},
    )


# --------------------------------------------------------------------------
# Land-cover segmentation
# --------------------------------------------------------------------------
def run_landcover_segmenter(ctx: RunContext, adaptive: bool = True,
                            role: str | None = None) -> ToolResult:
    scene = ctx.scenes.get(role) if role else ctx.get("primary", "after", "optical", "before")
    if scene is None:
        return ToolResult(tool="landcover_segmenter", tool_version=VERSION, status="skipped",
                          message="No optical scene is loaded.")
    # Multispectral is preferred, but a visible-only image is segmented through
    # the RGB proxy path rather than refused - see segment_landcover_rgb.
    if not IX.has_multispectral_bands(scene.bands) and not all(
            b in scene.bands for b in ("red", "green", "blue")):
        return ToolResult(
            tool="landcover_segmenter", tool_version=VERSION, status="no_data",
            message=("Segmentation needs NIR+Red (multispectral) or Red+Green+Blue "
                     f"(visible-only). This scene provides {sorted(scene.bands)}."))

    try:
        seg = IX.segment_landcover(scene.bands, scene.valid, adaptive=adaptive)
    except ValueError as exc:
        return ToolResult(tool="landcover_segmenter", tool_version=VERSION,
                          status="no_data", message=str(exc))
    ctx.cache[f"seg:{scene.role}"] = seg
    # A refused split is a finding, not a silent internal detail.
    for n in seg.notes:
        ctx.warn(n)

    src = scene.provenance.source
    facts = [fact(
        key=f"valid_pixels_{scene.role}", label=f"Observed pixels ({scene.label})",
        value=seg.valid_pixels, unit="pixels",
        method="pixels with a valid observation in the retrieved scene",
        tool="landcover_segmenter", source=src)]
    if ctx.georeferenced:
        facts.append(fact(
            key="scene_area_km2", label="Analysed area", value=round(ctx.scene_area_km2, 2),
            unit="km2", method="geodesic area of the requested bounding box",
            tool="landcover_segmenter", source=src))

    suffix = "" if scene.role in ("primary", "optical") else f"_{scene.role}"
    for name, frac in seg.fractions.items():
        if frac <= 0.0:
            continue
        facts.append(fact(
            key=f"{name}_fraction{suffix}", label=f"{IX.CLASS_LABELS[name]} share ({scene.label})",
            value=frac, unit="fraction",
            method=f"{seg.pixel_counts[name]} of {seg.valid_pixels} valid pixels; {seg.method}",
            tool="landcover_segmenter", source=src, sample_size=seg.valid_pixels))
        if ctx.georeferenced:
            facts.append(fact(
                key=f"{name}_area_km2{suffix}", label=f"{IX.CLASS_LABELS[name]} area ({scene.label})",
                value=ctx.area_of(seg.pixel_counts[name]), unit="km2",
                method=f"{seg.pixel_counts[name]} px x {ctx.pixel_area_km2:.6f} km2/px",
                tool="landcover_segmenter", source=src))

    overlay = IX.colorise_labels(seg.labels)
    legend = render.landcover_legend(seg.fractions)
    arts = [
        render.image_artifact(
            overlay, f"Land cover - {scene.label}", scene.bbox,
            description=f"Segmentation method: {seg.method}",
            provenance=scene.provenance, legend=legend, prefix="landcover"),
        render.bar_chart(
            f"Land-cover composition - {scene.label}",
            [r["label"] for r in legend], [r["value"] for r in legend],
            ylabel="% of observed area", colors=[r["color"] for r in legend],
            description=seg.method),
        render.table_artifact(
            f"Land-cover breakdown - {scene.label}",
            [{"key": "class", "label": "Class"}, {"key": "percent", "label": "% of scene"},
             {"key": "area_km2", "label": "Area (km²)"}, {"key": "pixels", "label": "Pixels"}],
            [{"class": IX.CLASS_LABELS[n], "percent": round(f * 100, 2),
              "area_km2": ctx.area_of(seg.pixel_counts[n]), "pixels": seg.pixel_counts[n]}
             for n, f in sorted(seg.fractions.items(), key=lambda kv: -kv[1]) if f > 0.0005],
            description=f"Total observed area {ctx.scene_area_km2:,.1f} km²."
            if ctx.georeferenced else "Scene is not georeferenced; areas in pixels."),
    ]
    # The visible-only basis is a weaker measurement and is reported as such,
    # both in the message and in the confidence the controller averages.
    rgb_basis = seg.basis == "rgb"
    return ToolResult(
        tool="landcover_segmenter", tool_version=VERSION, status="ok",
        message=(f"Segmented {seg.valid_pixels:,} valid pixels into "
                 f"{sum(1 for f in seg.fractions.values() if f > 0.001)} classes"
                 + (" using visible-band proxies (no NIR in this image)."
                    if rgb_basis else ".")),
        facts=facts, artifacts=arts, provenance=[scene.provenance],
        confidence=0.62 if rgb_basis else 0.82,
        parameters={"adaptive": adaptive, "thresholds": seg.thresholds,
                    "basis": seg.basis},
    )


# --------------------------------------------------------------------------
# RS-adapted scene classifier
# --------------------------------------------------------------------------
#: EuroSAT patches are 64 x 64 px of 10 m Sentinel-2, i.e. a 640 m footprint.
#: A model is only valid on imagery of comparable scale.
EUROSAT_GSD_M = 10.0
DOMAIN_GSD_LIMIT_M = 40.0


def _effective_gsd_m(ctx: RunContext, scene) -> float | None:
    """Ground sample distance of the analysis grid, in metres per pixel."""
    if not ctx.georeferenced:
        return scene.metadata.get("resolution_m")
    px_km2 = ctx.pixel_area_km2
    if px_km2 <= 0:
        return None
    return float((px_km2 ** 0.5) * 1000.0)


def run_rs_scene_classifier(ctx: RunContext, tile: int = 64, stride: int = 64,
                            max_tiles: int = 900) -> ToolResult:
    scene = ctx.get("primary", "after", "optical", "before")
    if scene is None:
        return ToolResult(tool="rs_scene_classifier", tool_version=VERSION, status="skipped",
                          message="No optical scene is loaded.")
    if not classifier.is_available():
        return ToolResult(
            tool="rs_scene_classifier", tool_version=VERSION, status="skipped",
            message=(f"Remote-sensing classifier unavailable: {classifier.load_error()}. "
                     "Run 'python -m app.ml.train_eurosat' to adapt it."))

    # ---- domain check: is this model even applicable to this imagery? -----
    gsd = _effective_gsd_m(ctx, scene)
    out_of_domain = gsd is not None and gsd > DOMAIN_GSD_LIMIT_M
    domain_note = None
    if out_of_domain:
        footprint_km = gsd * tile / 1000.0
        domain_note = (
            f"The classifier was adapted on EuroSAT ({EUROSAT_GSD_M:.0f} m Sentinel-2, so a "
            f"{tile}x{tile} patch covers {EUROSAT_GSD_M * tile / 1000:.2f} km). This scene is "
            f"{gsd:.0f} m per pixel, so the same patch covers {footprint_km:.1f} km - roughly "
            f"{gsd / EUROSAT_GSD_M:.0f}x coarser than anything the model was trained on. Its "
            "labels are reported as an out-of-domain indication only, with reduced confidence, "
            "and they are not used as the primary answer. The index-based segmentation, which "
            "is resolution-independent, is the authoritative land-cover result here."
        )
        ctx.warn(domain_note)

    try:
        res = classifier.classify_scene(scene.rgb, scene.valid, tile=tile,
                                        stride=stride, max_tiles=max_tiles)
    except Exception as exc:
        return ToolResult(tool="rs_scene_classifier", tool_version=VERSION, status="error",
                          message=f"Classification failed: {exc}")
    if res.get("status") != "ok":
        return ToolResult(tool="rs_scene_classifier", tool_version=VERSION, status="no_data",
                          message=res.get("message", "No classifiable tile."))

    info = classifier.model_info()
    src = f"{info['name']} v{info['version']} adapted on EuroSAT"
    # Out-of-domain output is still informative, but it must not masquerade as
    # a calibrated measurement: the label says so, and the confidence is cut.
    conf_scale = 0.35 if out_of_domain else 1.0
    tag = " [out-of-domain indication]" if out_of_domain else ""
    method_suffix = (f"; APPLIED OUT OF TRAINING DOMAIN at {gsd:.0f} m/px vs "
                     f"{EUROSAT_GSD_M:.0f} m training GSD" if out_of_domain else "")
    facts = [
        fact(key="rs_dominant_class",
             label=f"Dominant land-use class (EuroSAT taxonomy){tag}",
             value=res["dominant_class"],
             method=(f"most frequent class over {res['tiles']} classified "
                     f"{tile}x{tile} px tiles{method_suffix}"),
             tool="rs_scene_classifier", source=src,
             confidence=round(res["mean_confidence"] * conf_scale, 4)),
        fact(key="rs_dominant_fraction", label="Dominant class share of tiles",
             value=res["dominant_fraction"], unit="fraction",
             method=f"tiles of the dominant class / {res['tiles']} total tiles",
             tool="rs_scene_classifier", source=src, sample_size=res["tiles"]),
        fact(key="rs_tiles", label="Classified tiles", value=res["tiles"], unit="tiles",
             method=f"{tile}x{tile} px tiles with >=60% valid pixels",
             tool="rs_scene_classifier", source=src),
        fact(key="rs_mean_confidence", label="Mean classifier confidence",
             value=res["mean_confidence"], unit="probability",
             method="mean of per-tile maximum class probability",
             tool="rs_scene_classifier", source=src, sample_size=res["tiles"]),
        fact(key="rs_model_test_accuracy", label="Classifier held-out accuracy",
             value=info.get("test_accuracy") or 0.0, unit="fraction",
             method=(f"measured on {info.get('n_test')} held-out EuroSAT patches; "
                     f"{info.get('evaluation_protocol')}"),
             tool="rs_scene_classifier", source=info.get("citation")),
    ]
    for row in res["distribution"][:6]:
        facts.append(fact(
            key=f"rs_class_{row['class'].lower()}_fraction",
            label=f"{row['class']} tile share", value=row["fraction"], unit="fraction",
            method=f"{row['tiles']} of {res['tiles']} tiles, mean confidence {row['mean_confidence']}",
            tool="rs_scene_classifier", source=src, confidence=row["mean_confidence"]))

    grid = classifier.label_grid(res, scene.rgb.shape[:2], tile=tile)
    overlay = IX.colorise_labels(grid)
    arts = [
        render.image_artifact(
            overlay, f"RS classifier land use - {scene.label}", scene.bbox,
            description=((domain_note + " ") if out_of_domain else "")
                        + (f"Tile-wise EuroSAT classification mapped to coarse classes. "
                           f"Model held-out accuracy "
                           f"{(info.get('test_accuracy') or 0) * 100:.1f}% on its own domain."),
            provenance=scene.provenance,
            legend=render.landcover_legend(res["coarse_distribution"]), prefix="rsclass"),
        render.bar_chart(
            "EuroSAT class distribution", [r["class"] for r in res["distribution"]],
            [round(r["fraction"] * 100, 2) for r in res["distribution"]],
            ylabel="% of tiles",
            description=(f"{res['tiles']} tiles classified; mean confidence "
                         f"{res['mean_confidence']:.3f}.")),
        render.table_artifact(
            "Scene classification detail",
            [{"key": "class", "label": "EuroSAT class"},
             {"key": "description", "label": "Meaning"},
             {"key": "tiles", "label": "Tiles"},
             {"key": "percent", "label": "% of tiles"},
             {"key": "confidence", "label": "Mean conf."}],
            [{"class": r["class"], "description": r["description"], "tiles": r["tiles"],
              "percent": round(r["fraction"] * 100, 2), "confidence": r["mean_confidence"]}
             for r in res["distribution"]],
            description=(f"Model: {info.get('backend')} adapted on {info.get('adapted_on')}. "
                         f"Held-out accuracy {(info.get('test_accuracy') or 0) * 100:.2f}%, "
                         f"macro-F1 {info.get('macro_f1'):.3f}."
                         + (" " + domain_note if out_of_domain else ""))),
    ]
    res["out_of_domain"] = out_of_domain
    res["effective_gsd_m"] = gsd
    ctx.cache["rs_classification"] = res
    return ToolResult(
        tool="rs_scene_classifier", tool_version=VERSION, status="ok",
        message=(f"Classified {res['tiles']} tiles; dominant class "
                 f"'{res['dominant_class']}' ({res['dominant_fraction'] * 100:.1f}% of tiles)."
                 + (" Reported as an out-of-domain indication - see caveat." if out_of_domain
                    else "")),
        facts=facts, artifacts=arts, provenance=[scene.provenance],
        confidence=round(res["mean_confidence"] * conf_scale, 4),
        parameters={"tile": tile, "stride": stride, "max_tiles": max_tiles,
                    "model": info["name"], "model_version": info["version"],
                    "training_gsd_m": EUROSAT_GSD_M, "scene_gsd_m": gsd,
                    "out_of_domain": out_of_domain,
                    "domain_note": domain_note},
    )


# --------------------------------------------------------------------------
# Text-guided region grounding
# --------------------------------------------------------------------------
def run_region_grounder(ctx: RunContext, max_regions: int = 6, min_pixels: int = 40,
                        min_size: int = 12) -> ToolResult:
    scene = ctx.get("primary", "after", "optical", "before")
    if scene is None:
        return ToolResult(tool="region_grounder", tool_version=VERSION, status="skipped",
                          message="No optical scene is loaded.")

    targets = ctx.plan.target_classes or ["water"]
    target = targets[0]

    seg = ctx.cache.get(f"seg:{scene.role}")
    if seg is None:
        try:
            seg = IX.segment_landcover(scene.bands, scene.valid)
        except (ValueError, KeyError) as exc:
            return ToolResult(
                tool="region_grounder", tool_version=VERSION, status="no_data",
                message=(f"Cannot ground a region in this image: {exc}"))
        ctx.cache[f"seg:{scene.role}"] = seg

    if target not in IX.LANDCOVER_CLASSES:
        return ToolResult(
            tool="region_grounder", tool_version=VERSION, status="no_data",
            message=(f"'{target}' is not a class this system can ground. "
                     f"Supported: {list(IX.LANDCOVER_CLASSES)}."))

    ci = IX.LANDCOVER_CLASSES.index(target)
    raw_mask = seg.labels == ci
    if not raw_mask.any():
        return ToolResult(
            tool="region_grounder", tool_version=VERSION, status="no_data",
            message=(f"No pixel in this scene was classified as "
                     f"'{IX.CLASS_LABELS[target]}', so there is nothing to highlight. "
                     f"Detected classes: "
                     f"{[IX.CLASS_LABELS[k] for k, v in seg.fractions.items() if v > 0.005]}."))

    mask = RG.clean_mask(raw_mask, min_size=min_size, closing=1)
    if not mask.any():
        mask = raw_mask
        ctx.warn("All candidate regions were smaller than the speckle filter; "
                 "reporting the unfiltered mask.")

    labels, n = RG.connected_components(mask)
    regs = RG.region_boxes(labels, n, scene.bbox,
                           min_pixels=min_pixels, max_regions=max_regions)
    for r in regs:
        r.pop("_rows", None)
        r.pop("_cols", None)

    if not regs:
        return ToolResult(
            tool="region_grounder", tool_version=VERSION, status="no_data",
            message=(f"'{IX.CLASS_LABELS[target]}' pixels exist ({int(raw_mask.sum())} px) but no "
                     f"connected region reaches the {min_pixels}-pixel minimum size."))

    label = IX.CLASS_LABELS[target]
    src = scene.provenance.source
    total_px = int(mask.sum())
    facts = [
        fact(key=f"grounded_{target}_regions", label=f"{label} regions found",
             value=len(regs), unit="regions",
             method=f"8-connected components >= {min_pixels} px after speckle cleaning",
             tool="region_grounder", source=src),
        fact(key=f"grounded_{target}_pixels", label=f"{label} pixels", value=total_px,
             unit="pixels", method=f"pixels labelled '{target}' by {seg.method}",
             tool="region_grounder", source=src),
    ]
    if ctx.georeferenced:
        facts.append(fact(
            key=f"grounded_{target}_area_km2", label=f"Total {label.lower()} area",
            value=ctx.area_of(total_px), unit="km2",
            method=f"{total_px} px x {ctx.pixel_area_km2:.6f} km2/px",
            tool="region_grounder", source=src))
    for r in regs[:3]:
        facts.append(fact(
            key=f"grounded_{target}_region{r['rank']}_area_km2" if ctx.georeferenced
            else f"grounded_{target}_region{r['rank']}_pixels",
            label=f"{label} region #{r['rank']} size",
            value=RG.region_size(r, ctx.georeferenced),
            unit=ctx.area_unit(),
            method=f"connected component #{r['rank']}, centroid {RG.region_location(r)}",
            tool="region_grounder", source=src))

    overlay = np.zeros((*mask.shape, 4), dtype=np.uint8)
    cr, cg, cb = IX.CLASS_COLORS[target]
    overlay[mask] = (cr, cg, cb, 215)
    arts = [
        render.image_artifact(
            overlay, f"Grounded: {label}", scene.bbox,
            description=f"Pixels matching '{label}' in {scene.label}.",
            provenance=scene.provenance, prefix="ground"),
        render.boxes_artifact(
            f"{label} regions ({len(regs)})", regs, scene.bbox,
            description=("Ranked by area; boxes are geographic (EPSG:4326)."
                         if ctx.georeferenced else
                         "Ranked by size; boxes are in pixel coordinates because this "
                         "image carries no georeferencing."),
            provenance=scene.provenance),
        render.table_artifact(
            f"{label} regions",
            [{"key": "rank", "label": "#"},
             {"key": "area_km2", "label": f"Size ({ctx.area_unit()})"},
             {"key": "pixels", "label": "Pixels"},
             {"key": "centroid",
              "label": "Centroid (lon, lat)" if ctx.georeferenced else "Centroid (x, y px)"},
             {"key": "bbox",
              "label": "Bounding box" if ctx.georeferenced else "Bounding box (px)"}],
            [{"rank": r["rank"],
              "area_km2": RG.region_size(r, ctx.georeferenced),
              "pixels": r["pixels"],
              "centroid": RG.region_location(r),
              "bbox": RG.region_extent(r)} for r in regs]),
    ]
    return ToolResult(
        tool="region_grounder", tool_version=VERSION, status="ok",
        message=f"Grounded '{label}' to {len(regs)} region(s) covering {total_px:,} pixels.",
        facts=facts, artifacts=arts, provenance=[scene.provenance], confidence=0.8,
        answer=None,
        parameters={"target_class": target, "max_regions": max_regions,
                    "min_pixels": min_pixels, "min_size": min_size},
    )
