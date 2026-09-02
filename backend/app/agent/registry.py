"""The predefined model/tool registry.

The problem statement requires the controller to "select one or more models or
tools from a predefined registry" and "configure only permitted task
parameters". This module is that registry: a closed set of specialists, each
declaring which tasks it serves, which input configurations it accepts, which
modalities it needs, and exactly which parameters the controller may set.

:func:`validate_parameters` is the enforcement point - a parameter that is not
declared here cannot reach a tool, and a value outside the declared domain is
clamped and logged rather than silently accepted.
"""
from __future__ import annotations

from typing import Any, Callable

from ..ml import classifier
from ..schemas import InputConfiguration, TaskType, ToolSpec

# --------------------------------------------------------------------------
# Specifications
# --------------------------------------------------------------------------
SPECS: dict[str, ToolSpec] = {
    "rs_scene_classifier": ToolSpec(
        name="rs_scene_classifier",
        version="1.0.0",
        title="RS Scene Classifier (EuroSAT-adapted)",
        description=(
            "Tile-wise land-use classification using a gradient-boosted head trained "
            "on EuroSAT Sentinel-2 patches over a 196-dimensional remote-sensing "
            "feature representation (spectral moments, RGB vegetation/soil indices, "
            "multi-scale texture, spatial layout)."
        ),
        tasks=[TaskType.LANDCOVER, TaskType.CAPTION, TaskType.VQA,
               TaskType.OPTICAL_SAR_FUSION],
        input_configurations=[InputConfiguration.SINGLE, InputConfiguration.BITEMPORAL,
                              InputConfiguration.CROSS_MODAL],
        required_modalities=["optical"],
        permitted_parameters={
            "tile": {"type": "int", "default": 64, "choices": [32, 64, 128]},
            "stride": {"type": "int", "default": 64, "min": 16, "max": 256},
            "max_tiles": {"type": "int", "default": 900, "min": 50, "max": 4000},
        },
        backend="sklearn",
        adapted_on="EuroSAT RGB (Helber et al., 2019), 27,000 Sentinel-2 patches, 10 classes",
        citation="Helber et al., IEEE JSTARS 2019",
    ),
    "spectral_index": ToolSpec(
        name="spectral_index",
        version="1.0.0",
        title="Spectral Index Engine",
        description=(
            "Computes NDVI, NDWI, MNDWI, NBR, NDBI, BSI and VARI from the retrieved "
            "multispectral stack and reports full distribution statistics."
        ),
        tasks=[TaskType.INDEX_ANALYSIS, TaskType.VQA, TaskType.CAPTION,
               TaskType.LANDCOVER, TaskType.GROUNDING, TaskType.OPTICAL_SAR_FUSION],
        input_configurations=[InputConfiguration.SINGLE, InputConfiguration.BITEMPORAL],
        required_modalities=["optical"],
        permitted_parameters={
            "indices": {"type": "list[str]",
                        "choices": ["NDVI", "NDWI", "MNDWI", "NBR", "NDBI", "BSI", "VARI"]},
            "histogram_bins": {"type": "int", "default": 40, "min": 10, "max": 120},
        },
        backend="deterministic",
        citation="Rouse 1974; McFeeters 1996; Xu 2006; Key & Benson 2006; Zha 2003",
    ),
    "landcover_segmenter": ToolSpec(
        name="landcover_segmenter",
        version="1.0.0",
        title="Index-Threshold Land-Cover Segmenter",
        description=(
            "Per-pixel land-cover segmentation with an Otsu-adaptive water cut and "
            "literature-default vegetation/built-up cuts. Produces class fractions, "
            "real areas in km2 and a colourised overlay."
        ),
        tasks=[TaskType.LANDCOVER, TaskType.CAPTION, TaskType.VQA, TaskType.GROUNDING,
               TaskType.OPTICAL_SAR_FUSION, TaskType.INDEX_ANALYSIS],
        input_configurations=[InputConfiguration.SINGLE, InputConfiguration.BITEMPORAL,
                              InputConfiguration.CROSS_MODAL],
        required_modalities=["optical"],
        permitted_parameters={
            "adaptive": {"type": "bool", "default": True},
        },
        backend="deterministic",
        citation="Otsu 1979; Xu 2006",
    ),
    "region_grounder": ToolSpec(
        name="region_grounder",
        version="1.0.0",
        title="Text-Guided Region Grounder",
        description=(
            "Resolves a phrase in the query to a land-cover class mask, cleans it, "
            "extracts connected components, and returns geo-referenced bounding "
            "boxes and centroids ranked by area."
        ),
        tasks=[TaskType.GROUNDING, TaskType.VQA],
        input_configurations=[InputConfiguration.SINGLE, InputConfiguration.CROSS_MODAL],
        required_modalities=["optical"],
        permitted_parameters={
            "max_regions": {"type": "int", "default": 6, "min": 1, "max": 20},
            "min_pixels": {"type": "int", "default": 40, "min": 4, "max": 5000},
            "min_size": {"type": "int", "default": 12, "min": 1, "max": 2000},
        },
        backend="deterministic",
    ),
    "change_analyzer": ToolSpec(
        name="change_analyzer",
        version="1.0.0",
        title="Bi-Temporal Change Analyzer",
        description=(
            "Change Vector Analysis over the common band stack with an Otsu "
            "change/no-change cut, per-index delta maps, a class transition matrix "
            "and ranked change regions."
        ),
        tasks=[TaskType.CHANGE_DETECTION, TaskType.CHANGE_VQA],
        input_configurations=[InputConfiguration.BITEMPORAL],
        required_modalities=["optical"],
        permitted_parameters={
            "indices": {"type": "list[str]",
                        "choices": ["NDVI", "NDWI", "MNDWI", "NBR", "NDBI", "BSI", "VARI"]},
            "max_regions": {"type": "int", "default": 6, "min": 1, "max": 20},
            "min_pixels": {"type": "int", "default": 40, "min": 4, "max": 5000},
        },
        backend="deterministic",
        citation="Malila 1980 (Change Vector Analysis); Otsu 1979",
    ),
    "sar_analyzer": ToolSpec(
        name="sar_analyzer",
        version="1.0.0",
        title="SAR Backscatter Analyzer",
        description=(
            "Lee-filtered backscatter statistics, Otsu specular water detection and "
            "a brightness/texture built-up ranking on Sentinel-1 RTC imagery."
        ),
        tasks=[TaskType.OPTICAL_SAR_FUSION, TaskType.VQA, TaskType.CAPTION,
               TaskType.LANDCOVER, TaskType.GROUNDING],
        input_configurations=[InputConfiguration.SINGLE, InputConfiguration.CROSS_MODAL],
        required_modalities=["sar"],
        permitted_parameters={
            "despeckle": {"type": "bool", "default": True},
            "builtup_percentile": {"type": "float", "default": 80.0, "min": 50.0, "max": 99.0},
        },
        backend="deterministic",
        citation="Lee 1980 (speckle filter); Otsu 1979",
    ),
    "optical_sar_fusion": ToolSpec(
        name="optical_sar_fusion",
        version="1.0.0",
        title="Optical-SAR Fusion",
        description=(
            "Asserts co-registration, then combines optical MNDWI water evidence with "
            "SAR specular water evidence, reporting agreement (IoU), each sensor's "
            "unique detections and the area recovered under cloud by radar."
        ),
        tasks=[TaskType.OPTICAL_SAR_FUSION],
        input_configurations=[InputConfiguration.CROSS_MODAL],
        required_modalities=["optical", "sar"],
        permitted_parameters={
            "prefer_sar_under_cloud": {"type": "bool", "default": True},
        },
        backend="deterministic",
    ),
    "vqa_resolver": ToolSpec(
        name="vqa_resolver",
        version="1.0.0",
        title="Grounded VQA Resolver",
        description=(
            "Answers the question by looking the value up in the fact store produced "
            "by the measurement tools. It performs arithmetic and comparison over "
            "measured facts and refuses to answer when no fact covers the question."
        ),
        tasks=[TaskType.VQA, TaskType.CHANGE_VQA, TaskType.GROUNDING,
               TaskType.INDEX_ANALYSIS, TaskType.TIME_SERIES, TaskType.OPTICAL_SAR_FUSION,
               TaskType.CHANGE_DETECTION],
        input_configurations=list(InputConfiguration),
        permitted_parameters={},
        backend="deterministic",
    ),
    "scene_captioner": ToolSpec(
        name="scene_captioner",
        version="1.0.0",
        title="Grounded Scene Captioner",
        description=(
            "Composes a scene description strictly from measured class fractions, "
            "index statistics and classifier output. Every noun and every number is "
            "traceable to a fact."
        ),
        tasks=[TaskType.CAPTION],
        input_configurations=list(InputConfiguration),
        permitted_parameters={},
        backend="deterministic",
    ),
    "timeseries_analyzer": ToolSpec(
        name="timeseries_analyzer",
        version="1.0.0",
        title="Multi-Date Index Time Series",
        description=(
            "Retrieves the same AOI across many dates and builds a real index time "
            "series with an ordinary-least-squares trend, extremes and per-date "
            "coverage accounting."
        ),
        tasks=[TaskType.TIME_SERIES],
        input_configurations=[InputConfiguration.NONE, InputConfiguration.SINGLE],
        required_modalities=["optical"],
        # Retrieving the same area on other dates is impossible without knowing
        # which area it is, so this is a genuine geospatial prerequisite.
        requires_georeferencing=True,
        permitted_parameters={
            "steps": {"type": "int", "default": 8, "min": 3, "max": 24},
            "interval_days": {"type": "int", "default": 30, "min": 1, "max": 365},
            "index": {"type": "str", "default": "NDVI",
                      "choices": ["NDVI", "NDWI", "MNDWI", "NBR", "NDBI", "BSI", "VARI"]},
        },
        backend="deterministic",
    ),
}


# --------------------------------------------------------------------------
# Selection and validation
# --------------------------------------------------------------------------
def select_tools(task: TaskType, config: InputConfiguration,
                 modalities: list[str], georeferenced: bool = True) -> list[ToolSpec]:
    """All registry entries eligible for this task + input configuration.

    ``georeferenced`` gates only the tools that genuinely need a position on
    Earth. Everything else runs normally on an ordinary image and reports its
    results in pixel units.
    """
    out: list[ToolSpec] = []
    for spec in SPECS.values():
        if task not in spec.tasks:
            continue
        if config not in spec.input_configurations:
            continue
        if spec.required_modalities and not set(spec.required_modalities) <= set(modalities):
            continue
        if spec.requires_georeferencing and not georeferenced:
            continue
        out.append(spec)
    return out


def validate_parameters(tool: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop unpermitted keys, clamp out-of-range values, and report both."""
    spec = SPECS.get(tool)
    if spec is None:
        return {}, [f"unknown tool {tool!r}"]
    allowed = spec.permitted_parameters
    clean: dict[str, Any] = {}
    notes: list[str] = []

    for key, value in params.items():
        rule = allowed.get(key)
        if rule is None:
            notes.append(f"rejected parameter {key!r}: not permitted for {tool}")
            continue
        kind = rule.get("type", "str")
        try:
            if kind == "int":
                value = int(value)
            elif kind == "float":
                value = float(value)
            elif kind == "bool":
                value = bool(value)
            elif kind.startswith("list"):
                value = list(value)
        except (TypeError, ValueError):
            notes.append(f"rejected parameter {key!r}: cannot coerce to {kind}")
            continue

        if "choices" in rule:
            if kind.startswith("list"):
                kept = [v for v in value if v in rule["choices"]]
                if len(kept) != len(value):
                    notes.append(
                        f"clamped {key!r}: dropped {sorted(set(value) - set(kept))} "
                        "(not in permitted choices)"
                    )
                value = kept
            elif value not in rule["choices"]:
                notes.append(f"rejected parameter {key!r}={value!r}: not in {rule['choices']}")
                continue
        if "min" in rule and isinstance(value, (int, float)) and value < rule["min"]:
            notes.append(f"clamped {key!r} {value} -> {rule['min']} (below permitted minimum)")
            value = rule["min"]
        if "max" in rule and isinstance(value, (int, float)) and value > rule["max"]:
            notes.append(f"clamped {key!r} {value} -> {rule['max']} (above permitted maximum)")
            value = rule["max"]
        clean[key] = value

    for key, rule in allowed.items():
        if key not in clean and "default" in rule:
            clean[key] = rule["default"]
    return clean, notes


def registry_manifest() -> list[dict]:
    """Serialisable registry, enriched with live model status for the UI."""
    info = classifier.model_info()
    out: list[dict] = []
    for spec in SPECS.values():
        row = spec.model_dump()
        row["tasks"] = [t.value for t in spec.tasks]
        row["input_configurations"] = [c.value for c in spec.input_configurations]
        if spec.name == "rs_scene_classifier":
            row["status"] = "ready" if info["available"] else "not_trained"
            row["metrics"] = {
                "test_accuracy": info.get("test_accuracy"),
                "macro_f1": info.get("macro_f1"),
                "n_train": info.get("n_train"),
                "n_test": info.get("n_test"),
                "classes": info.get("classes"),
            }
            row["detail"] = info.get("error")
        else:
            row["status"] = "ready"
        out.append(row)
    return out
