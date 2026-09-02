"""The Query Analysis Summary must reflect the result and nothing else."""
from __future__ import annotations

from app.agent.grounding import FactStore, fact
from app.agent.summary import build_summary
from app.schemas import InputConfiguration, QueryPlan, TaskType


def _plan(**kw) -> QueryPlan:
    base = dict(raw_query="q", task=TaskType.CAPTION,
                input_configuration=InputConfiguration.SINGLE)
    base.update(kw)
    return QueryPlan(**base)


def _store(**values) -> FactStore:
    s = FactStore()
    for k, v in values.items():
        unit = "fraction" if k.endswith("_fraction") else (
            "km2" if k.endswith("_km2") else None)
        s.add(fact(key=k, label=k.replace("_", " ").title(), value=v,
                   method="test", tool="test", unit=unit))
    return s


def _titles(sections) -> list[str]:
    return [s.title for s in sections]


def _points(sections, title) -> list[str]:
    for s in sections:
        if s.title == title:
            return s.points
    return []


def test_pixel_space_image_gets_no_location_section():
    sections = build_summary(
        plan=_plan(aoi_name="Body"),          # a place name parsed from the question
        store=_store(water_fraction=0.3),
        status="ok",
        scene_meta={"spatial_reference": "pixel_space", "width": 10, "height": 10,
                    "bands": ["red", "green", "blue"], "is_upload": True},
    )
    assert "Location" not in _titles(sections)
    geo = _points(sections, "Geographic information")
    assert any("No geographic metadata" in p for p in geo)
    assert any("unaffected" in p for p in geo)


def test_georeferenced_image_reports_its_crs():
    sections = build_summary(
        plan=_plan(), store=_store(water_fraction=0.2), status="ok",
        scene_meta={"spatial_reference": "georeferenced", "width": 10, "height": 10,
                    "bands": ["red", "nir"], "bbox": [80.0, 12.0, 81.0, 13.0],
                    "metadata": {"crs": "EPSG:4326"}, "is_upload": True},
    )
    assert any("EPSG:4326" in p for p in _points(sections, "Geographic information"))
    assert "Location" in _titles(sections)


def test_unverified_place_name_is_not_shown_for_an_upload():
    sections = build_summary(
        plan=_plan(aoi_name="Body"), store=_store(water_fraction=0.2), status="ok",
        scene_meta={"spatial_reference": "georeferenced", "width": 10, "height": 10,
                    "bands": ["red"], "bbox": [80.0, 12.0, 81.0, 13.0], "is_upload": True},
    )
    assert not any("Body" in p for p in _points(sections, "Location"))


def test_summary_adapts_to_the_task():
    grounding = build_summary(
        plan=_plan(task=TaskType.GROUNDING, target_classes=["water"]),
        store=_store(grounded_water_regions=3, grounded_water_pixels=900,
                     water_fraction=0.25),
        status="ok", scene_meta={"spatial_reference": "pixel_space"},
    )
    assert any("region(s) located" in p for p in _points(grounding, "Key findings"))

    change = build_summary(
        plan=_plan(task=TaskType.CHANGE_DETECTION),
        store=_store(change_fraction=0.12, change_area_km2=45.0),
        status="ok", scene_meta={"spatial_reference": "georeferenced"},
    )
    findings = _points(change, "Key findings")
    assert any("changed" in p for p in findings)
    # The two tasks must not produce the same card.
    assert _points(grounding, "Key findings") != findings


def test_no_data_outcome_produces_a_short_honest_card():
    sections = build_summary(
        plan=_plan(task=TaskType.TIME_SERIES), store=_store(), status="no_data",
        answer="The required data is unavailable for this request.",
    )
    assert _titles(sections)[0] == "Outcome"
    assert any("No usable data" in p for p in _points(sections, "Outcome"))
    assert len(sections) <= 3


def test_summary_introduces_no_numbers_of_its_own():
    """Every numeral in the card must exist in the fact store."""
    import re

    store = _store(water_fraction=0.25, dense_vegetation_fraction=0.5)
    sections = build_summary(
        plan=_plan(), store=store, status="ok",
        scene_meta={"spatial_reference": "pixel_space", "width": 640, "height": 480,
                    "bands": ["red", "green", "blue"]},
    )
    allowed = {"0.25", "25", "25.0", "0.5", "50", "50.0", "640", "480", "3", "1"}
    for s in sections:
        for p in s.points:
            for tok in re.findall(r"\d+\.?\d*", p):
                assert tok in allowed, f"unexplained number {tok!r} in {p!r}"


def test_empty_sections_are_dropped_not_padded():
    sections = build_summary(
        plan=_plan(), store=_store(), status="ok", scene_meta={},
    )
    for s in sections:
        assert s.points, f"section {s.title} was emitted with no content"
