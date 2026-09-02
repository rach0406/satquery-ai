"""Short, search-box style queries must parse as well as written questions.

The failure these guard against is specific: before the intent layer existed,
"Kerala floods 2025" parsed as a generic scene description with no target
class, because no sentence pattern matched and the class table only listed the
singular "flood". Every case below is a phrasing a person would actually type.
"""
from __future__ import annotations

import pytest

from app.agent import intent, nlu
from app.schemas import TaskType


# --------------------------------------------------------------------------
# Event recognition
# --------------------------------------------------------------------------
@pytest.mark.parametrize("query,key", [
    ("Kerala floods 2025", "flood"),
    ("flooding in Assam", "flood"),
    ("Chennai cyclone", "cyclone"),
    ("California wildfire", "wildfire"),
    ("forest fire Uttarakhand", "wildfire"),
    ("India drought", "drought"),
    ("forest loss Amazon", "deforestation"),
    ("deforestation in the Amazon", "deforestation"),
    ("Hyderabad land change", "urban_growth"),
    ("urban growth Bengaluru", "urban_growth"),
    ("Gangotri glacier retreat", "glacier"),
    ("Wayanad landslide", "landslide"),
    ("Delhi air pollution", "air_quality"),
])
def test_event_is_recognised(query, key):
    event = intent.detect_event(query)
    assert event is not None, f"no event recognised in {query!r}"
    assert event.key == key


def test_no_event_for_a_neutral_question():
    assert intent.detect_event("Describe the land cover over the Sundarbans") is None


def test_plural_and_singular_forms_both_match():
    assert intent.detect_event("Kerala flood").key == "flood"
    assert intent.detect_event("Kerala floods").key == "flood"
    assert intent.detect_event("Kerala flooding").key == "flood"


# --------------------------------------------------------------------------
# Task selection
# --------------------------------------------------------------------------
def test_short_flood_query_becomes_water_grounding():
    plan = nlu.parse_rules("Kerala floods 2025")
    assert plan.task is TaskType.GROUNDING
    assert plan.aoi_name == "Kerala"
    assert "water" in plan.target_classes
    assert "MNDWI" in plan.indices
    assert plan.dates == ["2025-06-15"]


def test_short_change_query_becomes_change_detection():
    plan = nlu.parse_rules("Hyderabad land change")
    assert plan.task is TaskType.CHANGE_DETECTION
    assert plan.aoi_name == "Hyderabad"
    assert "built_up" in plan.target_classes


def test_two_dates_turn_a_hazard_into_a_comparison():
    """A single-date flood map and a two-date flood comparison are different
    questions, and supplying two dates is how a user asks for the second."""
    one = intent.interpret("Kerala floods 2025", date_count=1)
    two = intent.interpret("Kerala floods 2024 and 2025", date_count=2)
    assert one.task is TaskType.GROUNDING
    assert two.task is TaskType.CHANGE_DETECTION


def test_explicit_index_is_never_overridden_by_the_event():
    """The lexicon fills gaps; it does not overrule what the user actually said."""
    plan = nlu.parse_rules("NDVI over Kerala floods 2025")
    assert plan.indices == ["NDVI"]


def test_long_form_question_still_parses_the_old_way():
    plan = nlu.parse_rules("What changed around Chennai between January and October 2025?")
    assert plan.task is TaskType.CHANGE_DETECTION
    assert plan.aoi_name == "Chennai"
    assert plan.dates == ["2025-01-15", "2025-10-15"]


# --------------------------------------------------------------------------
# Honesty about scope
# --------------------------------------------------------------------------
def test_air_quality_is_declared_out_of_scope_rather_than_answered():
    plan = nlu.parse_rules("Delhi air pollution")
    assert plan.unsupported_aspect is not None
    assert "Sentinel-5P" in plan.unsupported_aspect
    # It still resolves the area and runs the observation it *can* make.
    assert plan.aoi_name == "Delhi"


def test_surface_temperature_is_declared_out_of_scope():
    plan = nlu.parse_rules("Mumbai temperature")
    assert plan.unsupported_aspect is not None
    assert "thermal" in plan.unsupported_aspect.lower()


def test_supported_query_carries_no_scope_warning():
    assert nlu.parse_rules("Kerala floods 2025").unsupported_aspect is None


# --------------------------------------------------------------------------
# Restatement
# --------------------------------------------------------------------------
def test_interpretation_names_only_resolved_fields():
    plan = nlu.parse_rules("Kerala floods 2025")
    text = plan.interpretation
    assert text and text.endswith(".")
    assert "Kerala" in text
    assert "2025" in text
    # It must not claim a location for a question that has none.
    empty = nlu.parse_rules("How much water is there?")
    assert "still needs to be named" in (empty.interpretation or "")


def test_upload_restatement_names_the_image_once():
    text = intent.restate(TaskType.CAPTION, None, [], None, [], on_upload=True)
    assert text.lower().count("upload") == 1


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
def test_conversational_padding_is_stripped_but_content_is_not():
    assert intent.normalise("Please show me Kerala floods 2025") == "Kerala floods 2025"
    assert intent.normalise("  Kerala   floods  2025 ") == "Kerala floods 2025"


def test_short_query_detection():
    assert intent.is_short_query("Kerala floods 2025")
    assert not intent.is_short_query(
        "Show me the flood-affected areas in Kerala during the 2025 monsoon season")
    assert not intent.is_short_query("What is it?")
