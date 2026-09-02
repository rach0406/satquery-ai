"""SAR specialists: backscatter analysis and cross-modal optical-SAR fusion."""
from __future__ import annotations

import numpy as np

from ..agent.context import RunContext
from ..agent.grounding import fact
from ..processing import indices as IX
from ..processing import regions as RG
from ..processing import sar as SAR
from ..schemas import ToolResult
from ..utils import render

VERSION = "1.0.0"


def run_sar_analyzer(ctx: RunContext, despeckle: bool = True,
                     builtup_percentile: float = 80.0) -> ToolResult:
    scene = ctx.get("sar")
    if scene is None:
        return ToolResult(tool="sar_analyzer", tool_version=VERSION, status="skipped",
                          message="No SAR scene is loaded for this request.")

    try:
        res = SAR.analyse_sar(scene.rgb, scene.valid, despeckle=despeckle,
                              builtup_percentile=builtup_percentile)
    except Exception as exc:
        return ToolResult(tool="sar_analyzer", tool_version=VERSION, status="error",
                          message=f"SAR analysis failed: {exc}")
    ctx.cache["sar"] = res

    src = scene.provenance.source
    s = res.stats
    facts = [
        fact(key="sar_mean_backscatter", label="Mean relative backscatter",
             value=s["mean_backscatter"], unit="relative gamma-0 (0-1)",
             method=f"mean over {s['valid_pixels']} valid pixels after {res.method}",
             tool="sar_analyzer", source=src, sample_size=s["valid_pixels"]),
        fact(key="sar_median_backscatter", label="Median relative backscatter",
             value=s["median_backscatter"], unit="relative gamma-0 (0-1)",
             method="median of the despeckled backscatter", tool="sar_analyzer", source=src),
        fact(key="sar_std_backscatter", label="Backscatter standard deviation",
             value=s["std_backscatter"], method="standard deviation over valid pixels",
             tool="sar_analyzer", source=src),
        fact(key="sar_water_fraction", label="SAR low-backscatter (water) share",
             value=s["water_fraction"], unit="fraction",
             method=(f"{s['water_pixels']} of {s['valid_pixels']} pixels below the Otsu "
                     f"specular cut at {res.water_threshold:.3f}"),
             tool="sar_analyzer", source=src, sample_size=s["valid_pixels"], confidence=0.85),
        fact(key="sar_water_pixels", label="SAR water pixels", value=s["water_pixels"],
             unit="pixels", method="pixels below the specular reflection threshold",
             tool="sar_analyzer", source=src),
        fact(key="sar_builtup_fraction", label="SAR built-up likelihood share",
             value=s["builtup_fraction"], unit="fraction",
             method=(f"{s['builtup_pixels']} pixels in the top "
                     f"{100 - builtup_percentile:.0f}% of the land brightness/texture score "
                     "(heuristic ranking, not a validated classifier)"),
             tool="sar_analyzer", source=src, sample_size=s["valid_pixels"], confidence=0.45),
        fact(key="sar_mean_texture", label="Mean backscatter texture (CV)",
             value=s["mean_texture"],
             method="mean local coefficient of variation in a 7x7 window",
             tool="sar_analyzer", source=src),
    ]
    if ctx.georeferenced:
        facts.append(fact(
            key="sar_water_area_km2", label="SAR-detected water area",
            value=ctx.area_of(s["water_pixels"]), unit="km2",
            method=f"{s['water_pixels']} px x {ctx.pixel_area_km2:.6f} km2/px",
            tool="sar_analyzer", source=src))

    hist, edges = np.histogram(res.backscatter[scene.valid], bins=48, range=(0.0, 1.0))
    arts = [
        render.image_artifact(
            render.stamp_scene(scene.rgb, np.where(scene.valid, 255, 0).astype(np.uint8)),
            f"SAR backscatter - {scene.label}", scene.bbox,
            description=f"{scene.provenance.source}, acquired {scene.date}. "
                        "Dark = smooth (water), bright = rough/built-up.",
            provenance=scene.provenance, prefix="sarimg"),
        render.image_artifact(
            SAR.colorise_sar_classes(res, scene.valid),
            "SAR classes (water / built-up)", scene.bbox,
            description=res.method, provenance=scene.provenance,
            legend=[{"label": "Water (specular)", "color": "rgb(37,99,235)"},
                    {"label": "Built-up (bright + rough)", "color": "rgb(244,114,182)"}],
            prefix="sarcls"),
        render.image_artifact(
            IX.colorise_index(res.texture, scene.valid, 0.0,
                              float(np.percentile(res.texture[scene.valid], 98)), "magma"),
            "SAR texture (local CV)", scene.bbox,
            description="Local coefficient of variation - high values indicate rough, "
                        "structurally complex surfaces such as urban fabric.",
            colormap="magma", prefix="sartex"),
        render.histogram_chart(
            "SAR backscatter distribution", [int(v) for v in hist],
            [float(v) for v in edges], xlabel="relative gamma-0 (0-1)", color="#d55181",
            marker_lines=[{"x": res.water_threshold,
                           "label": f"water cut {res.water_threshold:.3f}",
                           "color": "#3987e5"}]),
        render.table_artifact(
            "SAR backscatter statistics",
            [{"key": "metric", "label": "Metric"}, {"key": "value", "label": "Value"}],
            [{"metric": "Mean relative backscatter", "value": round(s["mean_backscatter"], 4)},
             {"metric": "Median", "value": round(s["median_backscatter"], 4)},
             {"metric": "Std deviation", "value": round(s["std_backscatter"], 4)},
             {"metric": "P10 / P90",
              "value": f"{s['p10_backscatter']:.4f} / {s['p90_backscatter']:.4f}"},
             {"metric": "Water share", "value": f"{s['water_fraction'] * 100:.2f}%"},
             {"metric": "Built-up share (heuristic)",
              "value": f"{s['builtup_fraction'] * 100:.2f}%"},
             {"metric": "Valid pixels", "value": f"{s['valid_pixels']:,}"}],
            description=" ".join(res.caveats)),
    ]
    for c in res.caveats:
        ctx.warn(c)

    return ToolResult(
        tool="sar_analyzer", tool_version=VERSION, status="ok",
        message=(f"SAR water share {s['water_fraction'] * 100:.2f}%, built-up likelihood "
                 f"{s['builtup_fraction'] * 100:.2f}% over {s['valid_pixels']:,} pixels."),
        facts=facts, artifacts=arts, provenance=[scene.provenance], confidence=0.72,
        parameters={"despeckle": despeckle, "builtup_percentile": builtup_percentile,
                    "water_threshold": round(res.water_threshold, 5)},
    )


def run_optical_sar_fusion(ctx: RunContext, prefer_sar_under_cloud: bool = True) -> ToolResult:
    optical = ctx.get("optical", "primary", "after")
    radar = ctx.get("sar")
    if optical is None or radar is None:
        missing = "optical" if optical is None else "SAR"
        return ToolResult(
            tool="optical_sar_fusion", tool_version=VERSION, status="skipped",
            message=f"Cross-modal fusion needs both sensors; the {missing} scene is missing.")

    coreg = SAR.check_coregistration(optical.shape, optical.bbox or [0, 0, 1, 1],
                                     radar.shape, radar.bbox or [0, 0, 1, 1])
    ctx.compatibility["optical_sar_coregistration"] = coreg
    if not coreg["co_registered"]:
        return ToolResult(
            tool="optical_sar_fusion", tool_version=VERSION, status="error",
            message=("The optical and SAR scenes are not co-registered "
                     f"(shapes {coreg['shape_a']} vs {coreg['shape_b']}, corner offset "
                     f"{coreg['max_corner_offset_deg']} deg). Fusion requires a common grid."),
            parameters={"coregistration": coreg})

    seg = ctx.cache.get(f"seg:{optical.role}")
    if seg is None:
        seg = IX.segment_landcover(optical.bands, optical.valid)
        ctx.cache[f"seg:{optical.role}"] = seg
    sar_res = ctx.cache.get("sar")
    if sar_res is None:
        sar_res = SAR.analyse_sar(radar.rgb, radar.valid)
        ctx.cache["sar"] = sar_res

    mask = optical.valid & radar.valid
    if mask.mean() < 0.02:
        return ToolResult(
            tool="optical_sar_fusion", tool_version=VERSION, status="no_data",
            message=(f"Only {mask.mean() * 100:.1f}% of the AOI was observed by both sensors, "
                     "which is too little to fuse."))

    wi = IX.LANDCOVER_CLASSES.index("water")
    ci = IX.LANDCOVER_CLASSES.index("cloud_or_snow")
    optical_water = seg.labels == wi
    cloud = seg.labels == ci

    fusion = SAR.fuse_optical_sar(
        optical_water, sar_res.water_mask, mask, ctx.pixel_area_km2,
        optical_cloud=cloud if prefer_sar_under_cloud else None)
    fusion.coregistration = coreg
    ctx.cache["fusion"] = fusion

    s = fusion.stats
    src = f"{optical.provenance.source} + {radar.provenance.source}"
    facts = [
        fact(key="fusion_iou", label="Optical-SAR water agreement (IoU)", value=s["iou"],
             method=(f"{s['agreement_pixels']} pixels flagged by both / "
                     f"{s['optical_water_pixels'] + s['sar_water_pixels'] - s['agreement_pixels']} "
                     "flagged by either"),
             tool="optical_sar_fusion", source=src, sample_size=s["valid_pixels"]),
        fact(key="fusion_optical_water_fraction", label="Optical water share",
             value=s["optical_water_fraction"], unit="fraction",
             method=f"{s['optical_water_pixels']} px from the MNDWI segmentation",
             tool="optical_sar_fusion", source=optical.provenance.source),
        fact(key="fusion_sar_water_fraction", label="SAR water share",
             value=s["sar_water_fraction"], unit="fraction",
             method=f"{s['sar_water_pixels']} px below the SAR specular threshold",
             tool="optical_sar_fusion", source=radar.provenance.source),
        fact(key="fusion_water_fraction", label="Fused water share",
             value=s["fused_water_fraction"], unit="fraction", method=fusion.method,
             tool="optical_sar_fusion", source=src, sample_size=s["valid_pixels"]),
        fact(key="fusion_optical_only_pixels", label="Water seen only by optical",
             value=s["optical_only_pixels"], unit="pixels",
             method="optical water mask minus SAR water mask",
             tool="optical_sar_fusion", source=src),
        fact(key="fusion_sar_only_pixels", label="Water seen only by SAR",
             value=s["sar_only_pixels"], unit="pixels",
             method="SAR water mask minus optical water mask",
             tool="optical_sar_fusion", source=src),
        fact(key="fusion_cloud_recovered_pixels",
             label="Water recovered under cloud by radar",
             value=s["cloud_recovered_pixels"], unit="pixels",
             method=("pixels the optical segmentation called cloud where SAR detected water - "
                     "the concrete benefit of the radar channel"),
             tool="optical_sar_fusion", source=src),
        fact(key="fusion_coobserved_pixels", label="Pixels seen by both sensors",
             value=s["valid_pixels"], unit="pixels",
             method="intersection of the optical and SAR validity masks",
             tool="optical_sar_fusion", source=src),
    ]
    if ctx.georeferenced:
        facts += [
            fact(key="fusion_water_km2", label="Fused water area", value=s["fused_water_km2"],
                 unit="km2", method=f"{s['fused_water_pixels']} px x "
                                    f"{ctx.pixel_area_km2:.6f} km2/px",
                 tool="optical_sar_fusion", source=src),
            fact(key="fusion_optical_water_km2", label="Optical-only water area estimate",
                 value=s["optical_water_km2"], unit="km2",
                 method="optical water pixel count converted to area",
                 tool="optical_sar_fusion", source=optical.provenance.source),
            fact(key="fusion_sar_water_km2", label="SAR water area estimate",
                 value=s["sar_water_km2"], unit="km2",
                 method="SAR water pixel count converted to area",
                 tool="optical_sar_fusion", source=radar.provenance.source),
            fact(key="fusion_cloud_recovered_km2", label="Area recovered under cloud",
                 value=s["cloud_recovered_km2"], unit="km2",
                 method="cloud-obscured pixels where SAR detected water",
                 tool="optical_sar_fusion", source=src),
        ]

    regs = RG.region_boxes(*RG.connected_components(RG.clean_mask(fusion.fused_water, 20)),
                           ctx.bbox, min_pixels=40, max_regions=6)
    for r in regs:
        r.pop("_rows", None)
        r.pop("_cols", None)

    arts = [
        render.image_artifact(
            render.stamp_scene(optical.rgb, np.where(optical.valid, 255, 0).astype(np.uint8)),
            f"Optical - {optical.label}", optical.bbox,
            description=f"{optical.provenance.source}, {optical.date}.",
            provenance=optical.provenance, prefix="optimg"),
        render.image_artifact(
            render.stamp_scene(radar.rgb, np.where(radar.valid, 255, 0).astype(np.uint8)),
            f"SAR - {radar.label}", radar.bbox,
            description=f"{radar.provenance.source}, {radar.date}.",
            provenance=radar.provenance, prefix="sarimg"),
        render.image_artifact(
            SAR.colorise_fusion(fusion, mask), "Optical-SAR water agreement", ctx.bbox,
            description=fusion.method,
            legend=[{"label": "Both sensors agree", "color": "rgb(25,158,112)"},
                    {"label": "Optical only", "color": "rgb(201,133,0)"},
                    {"label": "SAR only", "color": "rgb(213,81,129)"}],
            prefix="fusion"),
        render.bar_chart(
            "Water extent by sensor",
            ["Optical (MNDWI)", "SAR (specular)", "Both agree", "Fused"],
            [s["optical_water_km2"] if ctx.georeferenced else s["optical_water_pixels"],
             s["sar_water_km2"] if ctx.georeferenced else s["sar_water_pixels"],
             round(s["agreement_pixels"] * ctx.pixel_area_km2, 4) if ctx.georeferenced
             else s["agreement_pixels"],
             s["fused_water_km2"] if ctx.georeferenced else s["fused_water_pixels"]],
            ylabel=f"Water extent ({ctx.area_unit()})",
            colors=["#c98500", "#d55181", "#199e70", "#3987e5"],
            description=f"Agreement (IoU) between the two sensors: {s['iou']:.3f}."),
        render.table_artifact(
            "Cross-modal comparison",
            [{"key": "metric", "label": "Metric"}, {"key": "optical", "label": "Optical"},
             {"key": "sar", "label": "SAR"}, {"key": "fused", "label": "Fused"}],
            [{"metric": f"Water extent ({ctx.area_unit()})",
              "optical": s["optical_water_km2"] if ctx.georeferenced else s["optical_water_pixels"],
              "sar": s["sar_water_km2"] if ctx.georeferenced else s["sar_water_pixels"],
              "fused": s["fused_water_km2"] if ctx.georeferenced else s["fused_water_pixels"]},
             {"metric": "Water share of scene",
              "optical": f"{s['optical_water_fraction'] * 100:.2f}%",
              "sar": f"{s['sar_water_fraction'] * 100:.2f}%",
              "fused": f"{s['fused_water_fraction'] * 100:.2f}%"},
             {"metric": "Unique detections", "optical": f"{s['optical_only_pixels']:,} px",
              "sar": f"{s['sar_only_pixels']:,} px",
              "fused": f"{s['agreement_pixels']:,} px agreed"},
             {"metric": "Cloud-obscured area recovered", "optical": "n/a (cloud blocks optical)",
              "sar": f"{s['cloud_recovered_pixels']:,} px", "fused": "included"}],
            description=("Co-registration asserted: identical WMS BBOX/WIDTH/HEIGHT, "
                         f"max corner offset {coreg['max_corner_offset_deg']} deg.")),
        render.table_artifact(
            "Co-registration check",
            [{"key": "check", "label": "Check"}, {"key": "result", "label": "Result"}],
            [{"check": "Optical grid", "result": f"{coreg['shape_a'][1]} x {coreg['shape_a'][0]} px"},
             {"check": "SAR grid", "result": f"{coreg['shape_b'][1]} x {coreg['shape_b'][0]} px"},
             {"check": "Identical raster grid", "result": "PASS" if coreg["same_shape"] else "FAIL"},
             {"check": "Identical geographic extent",
              "result": "PASS" if coreg["same_extent"] else "FAIL"},
             {"check": "Max corner offset",
              "result": f"{coreg['max_corner_offset_deg']}°"},
             {"check": "CRS", "result": coreg["crs"]},
             {"check": "Co-registered", "result": "YES" if coreg["co_registered"] else "NO"}],
            description=coreg["method"]),
    ]
    if regs:
        arts.append(render.boxes_artifact(
            f"Fused water bodies ({len(regs)})", regs, ctx.bbox,
            description="Connected components of the fused water mask."))

    return ToolResult(
        tool="optical_sar_fusion", tool_version=VERSION, status="ok",
        message=(f"Fused optical and SAR water evidence: IoU {s['iou']:.3f}, fused water share "
                 f"{s['fused_water_fraction'] * 100:.2f}%, {s['cloud_recovered_pixels']:,} px "
                 "recovered under cloud."),
        facts=facts, artifacts=arts,
        provenance=[optical.provenance, radar.provenance], confidence=0.75,
        parameters={"prefer_sar_under_cloud": prefer_sar_under_cloud,
                    "coregistration": coreg},
    )
