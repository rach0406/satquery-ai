"""The grounding gate is the project's central claim, so it gets the most tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.grounding import FactStore, build_report, fact, verify_text  # noqa: E402
from app.schemas import DataOrigin, Provenance  # noqa: E402


@pytest.fixture()
def store() -> FactStore:
    s = FactStore()
    s.add(fact("water_fraction", "Water share", 0.2841, "MNDWI segmentation", "seg",
               unit="fraction"))
    s.add(fact("water_area_km2", "Water area", 1021.55, "pixels x km2/px", "seg", unit="km2"))
    s.add(fact("ndvi_mean", "NDVI mean", 0.3617, "mean over valid pixels", "idx"))
    s.add(fact("veg_delta_km2", "Vegetation change", -1059.17, "after minus before", "chg",
               unit="km2"))
    s.add_provenance([Provenance(origin=DataOrigin.LIVE_SATELLITE, source="NASA GIBS / MODIS")])
    return s


def test_exact_value_is_verified(store):
    ok, bad = verify_text("NDVI mean is 0.3617.", store)
    assert not bad
    assert ok[0].matched_fact == "ndvi_mean"


def test_fraction_may_be_quoted_as_percentage(store):
    ok, bad = verify_text("Water covers 28.41% of the scene.", store)
    assert not bad
    assert ok[0].matched_fact == "water_fraction"


def test_signed_fact_may_be_quoted_as_magnitude(store):
    """Prose says 'shrank by 1,059.17 km²'; the fact keeps the sign."""
    ok, bad = verify_text("Vegetation shrank by 1,059.17 km2.", store)
    assert not bad
    assert ok[0].matched_fact == "veg_delta_km2"


def test_invented_number_is_rejected(store):
    _, bad = verify_text("Water covers 63.20% of the scene.", store)
    assert [c.text for c in bad] == ["63.20"]


def test_plausible_but_unmeasured_number_is_rejected(store):
    """The whole point: a number close to nothing measured must not slip through."""
    _, bad = verify_text("The lake holds roughly 4200 million cubic metres.", store)
    assert bad and bad[0].value == 4200


def test_structural_numbers_are_not_treated_as_claims(store):
    """Raster dimensions, ordinals, dates and CRS codes are not measurements."""
    text = ("Acquired 2025-10-14 by MODIS at 512x512 pixels in EPSG:4326, "
            "the 10th-90th percentile range was reported.")
    ok, bad = verify_text(text, store)
    assert not bad, [c.text for c in bad]


def test_strict_mode_replaces_a_failing_narration(store):
    llm = "Water covers 99.90% of the scene."
    template = "Water covers 28.41% of the scene."
    final, report = build_report(llm, store, "llm", fallback_text=template)
    assert final == template
    assert report.narrator == "llm_rejected_fallback_template"
    assert report.passed


def test_clean_llm_narration_is_kept(store):
    llm = "Water covers 28.41% of the scene and mean NDVI is 0.3617."
    final, report = build_report(llm, store, "llm", fallback_text="fallback")
    assert final == llm
    assert report.narrator == "llm"
    assert report.claims_verified == 2


def test_store_reports_real_sources(store):
    assert store.all_real is True
    store.add_provenance([Provenance(origin=DataOrigin.SYNTHETIC_DEMO, source="fake")])
    assert store.all_real is False
