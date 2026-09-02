"""NLU, registry, processing and end-to-end API tests.

Tests that reach the NASA archive are marked ``network`` and can be skipped:

    pytest -m "not network"
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import nlu, registry  # noqa: E402
from app.datasources import gazetteer  # noqa: E402
from app.processing import change as CH  # noqa: E402
from app.processing import indices as IX  # noqa: E402
from app.processing import regions as RG  # noqa: E402
from app.processing import sar as SAR  # noqa: E402
from app.schemas import InputConfiguration, TaskType  # noqa: E402


# --------------------------------------------------------------------------
# NLU
# --------------------------------------------------------------------------
@pytest.mark.parametrize("query,task", [
    ("What changed around Chennai between January 2025 and October 2025?",
     TaskType.CHANGE_DETECTION),
    ("Use the optical and SAR images together to map water in the Sundarbans",
     TaskType.OPTICAL_SAR_FUSION),
    ("Highlight the water body in Chilika Lake", TaskType.GROUNDING),
    ("Describe the land cover over Kolkata", TaskType.CAPTION),
    ("What is the mean NDVI over the Western Ghats?", TaskType.INDEX_ANALYSIS),
    ("Show me the NDVI trend over the last 8 months in Kerala", TaskType.TIME_SERIES),
    ("Has the built-up area in Delhi increased since 2020?", TaskType.CHANGE_VQA),
])
def test_task_classification(query, task):
    assert nlu.parse_rules(query, allow_online_geocode=False).task is task


def test_change_query_sets_bitemporal_configuration():
    plan = nlu.parse_rules("Compare Chennai between 2020 and 2024", allow_online_geocode=False)
    assert plan.input_configuration is InputConfiguration.BITEMPORAL
    assert len(plan.dates) == 2


@pytest.mark.parametrize("text,expected", [
    ("October 2025", ["2025-10-15"]),
    ("15 March 2024", ["2024-03-15"]),
    ("2024-07-04", ["2024-07-04"]),
    ("between 2019 and 2023", ["2019-06-15", "2023-06-15"]),
    ("in 1985", ["1985-06-15"]),
])
def test_date_extraction(text, expected):
    assert [h.iso for h in nlu.extract_dates(text)] == expected


def test_dates_are_never_in_the_future():
    hits = nlu.extract_dates("in 2026")
    assert all(h.iso <= date.today().isoformat() for h in hits)


def test_target_class_and_index_inference():
    plan = nlu.parse_rules("How much flooding is there in Kochi?", allow_online_geocode=False)
    assert "water" in plan.target_classes
    assert "MNDWI" in plan.indices


# --------------------------------------------------------------------------
# Gazetteer
# --------------------------------------------------------------------------
def test_known_place_resolves_offline():
    p = gazetteer.resolve("flooding in Chennai last week", allow_online=False)
    assert p and p.name == "Chennai"
    assert len(p.bbox) == 4


def test_partial_word_does_not_match_a_place():
    assert gazetteer.lookup_offline("puneet went home") is None


@pytest.mark.parametrize("text", [
    "How much water is there?",
    "show me the trend",
    "what is the ndvi",
    "describe the change",
])
def test_questions_without_a_place_do_not_geocode(text):
    """Nominatim matches almost any word; refusing is the correct behaviour."""
    assert gazetteer.resolve(text, allow_online=True) is None


def test_bbox_area_is_sane():
    # One degree square at the equator is roughly 12,300 km2.
    assert 11_000 < gazetteer.bbox_area_km2((0, 0, 1, 1)) < 13_000


# --------------------------------------------------------------------------
# Indices and segmentation
# --------------------------------------------------------------------------
def _synthetic_bands(n=64):
    """Half water, half vegetation - a scene with a known correct answer."""
    z = np.zeros((n, n), dtype=np.float32)
    bands = {k: z.copy() for k in ("blue", "green", "red", "nir", "swir2")}
    half = n // 2
    # water: high green, low NIR, very low SWIR
    bands["green"][:half] = 0.30
    bands["red"][:half] = 0.12
    bands["nir"][:half] = 0.05
    bands["swir2"][:half] = 0.02
    bands["blue"][:half] = 0.28
    # vegetation: low red, high NIR
    bands["green"][half:] = 0.14
    bands["red"][half:] = 0.07
    bands["nir"][half:] = 0.55
    bands["swir2"][half:] = 0.20
    bands["blue"][half:] = 0.06
    return bands


def test_ndvi_matches_the_definition():
    b = _synthetic_bands()
    ndvi = IX.compute_index("NDVI", b)
    expected = (0.55 - 0.07) / (0.55 + 0.07)
    assert np.allclose(ndvi[40, 10], expected, atol=1e-5)


def test_missing_band_raises_rather_than_guessing():
    with pytest.raises(KeyError):
        IX.compute_index("MNDWI", {"nir": np.zeros((4, 4)), "red": np.zeros((4, 4))})


def test_segmentation_finds_the_known_split():
    b = _synthetic_bands()
    mask = np.ones((64, 64), dtype=bool)
    seg = IX.segment_landcover(b, mask)
    assert seg.fractions["water"] == pytest.approx(0.5, abs=0.06)
    veg = seg.fractions["dense_vegetation"] + seg.fractions["sparse_vegetation"]
    assert veg == pytest.approx(0.5, abs=0.06)


def test_uniform_scene_is_not_split_into_invented_classes():
    """Otsu always returns a cut; the separability gate must refuse this one."""
    n = 48
    flat = {k: np.full((n, n), v, dtype=np.float32) for k, v in
            (("blue", 0.30), ("green", 0.33), ("red", 0.35), ("nir", 0.36), ("swir2", 0.40))}
    rng = np.random.RandomState(0)
    for k in flat:
        flat[k] = flat[k] + rng.normal(0, 0.004, (n, n)).astype(np.float32)
    seg = IX.segment_landcover(flat, np.ones((n, n), dtype=bool))
    assert seg.fractions["water"] < 0.02
    assert seg.fractions["bare_soil"] > 0.9


def test_otsu_separability_distinguishes_bimodal_from_unimodal():
    bimodal = np.concatenate([np.random.RandomState(1).normal(0.1, 0.02, 2000),
                              np.random.RandomState(2).normal(0.8, 0.02, 2000)])
    unimodal = np.random.RandomState(3).normal(0.5, 0.02, 4000)
    _, eta_b = IX.otsu_with_separability(bimodal)
    _, eta_u = IX.otsu_with_separability(unimodal)
    assert eta_b > 0.9
    # Otsu on a single Gaussian cuts at the mean, giving exactly 2/pi.
    assert eta_u == pytest.approx(IX.UNIMODAL_GAUSSIAN_ETA, abs=0.02)


def test_bimodality_gates_sit_above_the_unimodal_floor():
    """A gate at or below 2/pi could never reject a unimodal population."""
    assert IX.BIMODALITY_MIN > IX.UNIMODAL_GAUSSIAN_ETA
    assert IX.BUILTUP_SEPARABILITY_MIN > IX.BIMODALITY_MIN


def test_index_stats_ignore_masked_pixels():
    arr = np.full((10, 10), 0.5, dtype=np.float32)
    arr[0, :] = 99.0
    mask = np.ones((10, 10), dtype=bool)
    mask[0, :] = False
    st = IX.index_stats(arr, mask, "NDVI")
    assert st.mean == pytest.approx(0.5)
    assert st.valid_pixels == 90


# --------------------------------------------------------------------------
# Change detection
# --------------------------------------------------------------------------
def test_change_detection_finds_a_planted_change():
    a = _synthetic_bands()
    b = {k: v.copy() for k, v in a.items()}
    b["nir"][50:60, 10:30] = 0.05   # vegetation cleared
    b["red"][50:60, 10:30] = 0.30
    mask = np.ones((64, 64), dtype=bool)
    res = CH.analyse_change(a, b, mask, pixel_area_km2=0.01)
    assert res.changed_pixels >= 180
    assert res.index_delta_stats["NDVI"]["mean"] < 0


def test_identical_scenes_report_no_meaningful_change():
    a = _synthetic_bands()
    res = CH.analyse_change(a, {k: v.copy() for k, v in a.items()},
                            np.ones((64, 64), dtype=bool))
    assert res.changed_fraction == 0.0


# --------------------------------------------------------------------------
# Regions
# --------------------------------------------------------------------------
def test_connected_components_and_georeferencing():
    m = np.zeros((40, 40), dtype=bool)
    m[5:15, 5:15] = True
    m[25:35, 25:35] = True
    labels, n = RG.connected_components(m)
    assert n == 2
    boxes = RG.region_boxes(labels, n, [70.0, 20.0, 71.0, 21.0], min_pixels=10)
    assert len(boxes) == 2
    assert all(70.0 <= b["centroid"][0] <= 71.0 for b in boxes)
    assert all(20.0 <= b["centroid"][1] <= 21.0 for b in boxes)


def test_pixel_to_lonlat_corners():
    bbox = [70.0, 20.0, 71.0, 21.0]
    lon, lat = RG.pixel_to_lonlat(bbox, (100, 100), 0, 0)
    assert lon == pytest.approx(70.005, abs=1e-3)
    assert lat == pytest.approx(20.995, abs=1e-3)   # row 0 is the north edge


# --------------------------------------------------------------------------
# SAR + fusion
# --------------------------------------------------------------------------
def test_sar_water_detection_and_coregistration():
    n = 64
    rgb = np.full((n, n, 3), 180, dtype=np.uint8)
    rgb[:20] = 8                       # smooth water: specular, very dark
    mask = np.ones((n, n), dtype=bool)
    res = SAR.analyse_sar(rgb, mask)
    assert res.stats["water_fraction"] == pytest.approx(20 / 64, abs=0.08)

    coreg = SAR.check_coregistration((n, n), [0, 0, 1, 1], (n, n), [0, 0, 1, 1])
    assert coreg["co_registered"]
    assert not SAR.check_coregistration((n, n), [0, 0, 1, 1],
                                        (32, 32), [0, 0, 1, 1])["co_registered"]


def test_fusion_reports_agreement_and_cloud_recovery():
    n = 32
    mask = np.ones((n, n), dtype=bool)
    optical = np.zeros((n, n), dtype=bool)
    optical[:10] = True
    radar = np.zeros((n, n), dtype=bool)
    radar[:10] = True
    radar[20:24] = True                # water the optical sensor could not see
    cloud = np.zeros((n, n), dtype=bool)
    cloud[20:24] = True
    f = SAR.fuse_optical_sar(optical, radar, mask, 0.01, optical_cloud=cloud)
    assert f.stats["cloud_recovered_pixels"] == 4 * n
    assert 0.0 < f.agreement < 1.0
    assert f.stats["fused_water_pixels"] == 14 * n


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
def test_registry_rejects_unpermitted_parameters():
    clean, notes = registry.validate_parameters(
        "spectral_index", {"indices": ["NDVI"], "secret_backdoor": 1})
    assert "secret_backdoor" not in clean
    assert any("secret_backdoor" in n for n in notes)


def test_registry_clamps_out_of_range_values():
    clean, notes = registry.validate_parameters("region_grounder", {"max_regions": 9999})
    assert clean["max_regions"] == 20
    assert any("clamped" in n for n in notes)


def test_registry_drops_unknown_choices():
    clean, notes = registry.validate_parameters(
        "spectral_index", {"indices": ["NDVI", "NOT_AN_INDEX"]})
    assert clean["indices"] == ["NDVI"]
    assert any("NOT_AN_INDEX" in n for n in notes)


def test_registry_applies_declared_defaults():
    clean, _ = registry.validate_parameters("sar_analyzer", {})
    assert clean["despeckle"] is True
    assert clean["builtup_percentile"] == 80.0


def test_tool_selection_respects_modality_requirements():
    optical_only = registry.select_tools(
        TaskType.OPTICAL_SAR_FUSION, InputConfiguration.CROSS_MODAL, ["optical"])
    assert "optical_sar_fusion" not in {s.name for s in optical_only}

    both = registry.select_tools(
        TaskType.OPTICAL_SAR_FUSION, InputConfiguration.CROSS_MODAL, ["optical", "sar"])
    assert "optical_sar_fusion" in {s.name for s in both}


def test_every_registered_tool_has_an_implementation():
    from app.agent.controller import TOOL_IMPL

    assert set(registry.SPECS) == set(TOOL_IMPL)


def test_every_workflow_step_is_a_registered_tool():
    from app.agent.controller import WORKFLOWS

    for task, steps in WORKFLOWS.items():
        for step in steps:
            assert step in registry.SPECS, f"{task.value} references unknown tool {step}"
