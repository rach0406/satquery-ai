"""Short-query interpretation: turning a search box into an analysis request.

The rule parser in :mod:`app.agent.nlu` reads *sentences* well - it looks for
"what changed between", "highlight the", "describe this". Real users do not
type sentences into a search box. They type::

    Kerala floods 2025
    Hyderabad land change
    California wildfire
    forest loss Amazon

Every one of those parsed as "scene description with no target class", because
none of them contains a task verb and the class table only listed the singular
"flood". The result was a generic land-cover readout for a question that was
plainly about water.

This module fixes that at the level it should be fixed: a small **event
lexicon**. Each entry recognises a real-world phenomenon and states what
analysing it actually means in remote sensing - which task, which land-cover
classes, which spectral indices, which sensors. That mapping is the domain
knowledge; the pipeline downstream is unchanged.

Two rules keep this honest:

* It only ever fills in fields the query left *empty*. An explicit "NDVI" or
  "change detection" in the text always wins.
* Nothing is invented about the world. Recognising "flood" selects a water
  index; it does not assert that a flood happened. Phenomena the sensors here
  genuinely cannot measure (air quality, for one) are recorded in
  :attr:`Interpretation.unsupported` so the answer can say so instead of
  quietly analysing something else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas import TaskType

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
#: Chat-style noise that carries no analytical meaning.
_FILLER = re.compile(
    r"\b(please|kindly|hey|hi|hello|can you|could you|would you|i want to|"
    r"i would like to|i need|give me|show me|tell me|pls|plz)\b", re.I)

_WHITESPACE = re.compile(r"\s+")


def normalise(query: str) -> str:
    """Trim conversational padding and collapse whitespace.

    Deliberately conservative: it removes politeness and nothing else, so the
    normalised string still contains every word the parsers key on.
    """
    text = _FILLER.sub(" ", query or "")
    text = text.replace("&", " and ")
    return _WHITESPACE.sub(" ", text).strip()


def is_short_query(query: str) -> bool:
    """A keyword-style search rather than a written question."""
    words = normalise(query).split()
    return len(words) <= 5 and "?" not in query


# --------------------------------------------------------------------------
# Event lexicon
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """One recognisable real-world phenomenon and how to analyse it."""

    key: str
    label: str                       #: shown to the user, e.g. "Flood / surface water"
    patterns: tuple[str, ...]        #: regexes matched against the normalised query
    task: TaskType                   #: task to use when the query names no other
    #: Task to prefer when the query supplies two dates - most hazards are far
    #: better answered as "what changed" than as a single snapshot.
    bitemporal_task: TaskType | None = None
    classes: tuple[str, ...] = ()
    indices: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    #: How the request is restated back to the user in plain English.
    reads_as: str = ""
    #: Set when the sensors in this system cannot measure the phenomenon.
    unsupported: str | None = None
    priority: int = 50


EVENTS: tuple[Event, ...] = (
    Event(
        key="flood", label="Flood / surface water",
        patterns=(r"\bflood(s|ed|ing)?\b", r"\binundat(ion|ed|ing)\b",
                  r"\bdeluge\b", r"\bwater ?logg(ed|ing)\b", r"\bsubmerged\b",
                  r"\boverflow(ed|ing)?\b", r"\bbreach(ed|es)?\b"),
        task=TaskType.GROUNDING, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("water",), indices=("MNDWI", "NDWI"), modalities=("optical",),
        reads_as="map the surface-water extent (flood mapping)",
        priority=95,
    ),
    Event(
        key="cyclone", label="Cyclone / storm impact",
        patterns=(r"\bcyclon(e|es|ic)\b", r"\bhurricane(s)?\b", r"\btyphoon(s)?\b",
                  r"\bstorm surge\b", r"\bstorm(s)?\b", r"\bdepression\b"),
        task=TaskType.GROUNDING, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("water",), indices=("MNDWI",), modalities=("optical",),
        reads_as="map storm-related surface water and coastal inundation",
        priority=88,
    ),
    Event(
        key="wildfire", label="Wildfire / burn severity",
        patterns=(r"\bwild ?fire(s)?\b", r"\bforest fire(s)?\b", r"\bbush ?fire(s)?\b",
                  r"\bburn(t|ed|ing)?\b", r"\bfire scar(s)?\b", r"\bblaze\b",
                  r"\bfire(s)?\b"),
        task=TaskType.INDEX_ANALYSIS, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("bare_soil", "dense_vegetation"), indices=("NBR", "NDVI"),
        modalities=("optical",),
        reads_as="measure burn severity from the normalised burn ratio",
        priority=90,
    ),
    Event(
        key="drought", label="Drought / vegetation stress",
        patterns=(r"\bdrought(s)?\b", r"\bdry spell\b", r"\bwater (scarcity|stress)\b",
                  r"\bparched\b", r"\bdesertif(ication|ying)\b",
                  r"\bcrop (stress|failure)\b"),
        task=TaskType.INDEX_ANALYSIS, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("sparse_vegetation", "bare_soil"), indices=("NDVI", "NDWI"),
        modalities=("optical",),
        reads_as="measure vegetation vigour and surface dryness",
        priority=85,
    ),
    Event(
        key="deforestation", label="Forest loss",
        patterns=(r"\bdeforest(ation|ed)?\b", r"\bforest (loss|cover loss|clearing)\b",
                  r"\btree (loss|cover loss)\b", r"\blogging\b",
                  r"\bforest degradation\b", r"\bclear ?cut(ting)?\b"),
        task=TaskType.CHANGE_DETECTION, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("dense_vegetation",), indices=("NDVI",), modalities=("optical",),
        reads_as="compare forest cover between two dates",
        priority=92,
    ),
    Event(
        key="urban_growth", label="Urban / land-use change",
        patterns=(r"\burban(isation|ization|\s+growth|\s+sprawl|\s+expansion)?\b",
                  r"\bland ?use change\b", r"\bland change\b", r"\bland cover change\b",
                  r"\bbuilt[- ]?up (growth|change|expansion)\b",
                  r"\bconstruction\b", r"\bencroach(ment|ed)\b",
                  r"\bcity (growth|expansion)\b", r"\bdevelopment\b"),
        task=TaskType.CHANGE_DETECTION, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("built_up",), indices=("NDBI", "NDVI"), modalities=("optical",),
        reads_as="compare built-up extent between two dates",
        priority=86,
    ),
    Event(
        key="glacier", label="Snow, ice and glacier change",
        patterns=(r"\bglacier(s)?\b", r"\bsnow ?(cover|melt|line)?\b", r"\bice (melt|cover)\b",
                  r"\bretreat(ing)?\b", r"\bavalanche\b"),
        task=TaskType.CHANGE_DETECTION, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("cloud_or_snow",), indices=("NDWI", "NDVI"), modalities=("optical",),
        reads_as="compare snow and ice extent between two dates",
        priority=84,
    ),
    Event(
        key="landslide", label="Landslide / terrain scar",
        patterns=(r"\bland ?slide(s)?\b", r"\bmud ?slide(s)?\b", r"\bdebris flow\b",
                  r"\bslope failure\b", r"\brock ?fall\b"),
        task=TaskType.CHANGE_DETECTION, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("bare_soil", "dense_vegetation"), indices=("NDVI", "BSI"),
        modalities=("optical",),
        reads_as="find newly exposed ground against the previous vegetation cover",
        priority=87,
    ),
    Event(
        key="agriculture", label="Crop and vegetation health",
        patterns=(r"\bcrop(s|land)?\b", r"\bagricultur(e|al)\b", r"\bfarm(land|ing)?\b",
                  r"\bharvest(ing)?\b", r"\byield\b", r"\bkharif\b", r"\brabi\b",
                  r"\bsowing\b", r"\bplantation(s)?\b", r"\birrigation\b",
                  r"\bvegetation health\b", r"\bgreenery\b", r"\bgreen cover\b"),
        task=TaskType.INDEX_ANALYSIS, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("sparse_vegetation",), indices=("NDVI",), modalities=("optical",),
        reads_as="measure vegetation vigour over cropland",
        priority=70,
    ),
    Event(
        key="water_body", label="Water-body extent",
        patterns=(r"\b(lake|reservoir|dam|pond|tank)s?\b", r"\bwater (level|body|bodies)\b",
                  r"\bshrink(ing|age)?\b", r"\bdry(ing)? up\b", r"\bwater spread\b",
                  r"\bwetland(s)?\b", r"\bbackwater(s)?\b"),
        task=TaskType.GROUNDING, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("water",), indices=("MNDWI", "NDWI"), modalities=("optical",),
        reads_as="delineate the water body and measure its extent",
        priority=72,
    ),
    Event(
        key="coastal", label="Coastline / shoreline change",
        patterns=(r"\bcoast(al|line)?\b", r"\bshore ?line\b", r"\berosion\b",
                  r"\bbeach\b", r"\bestuary\b", r"\bdelta\b"),
        task=TaskType.GROUNDING, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("water",), indices=("MNDWI",), modalities=("optical",),
        reads_as="delineate the land-water boundary",
        priority=68,
    ),
    Event(
        key="mining", label="Mining / bare ground",
        patterns=(r"\bmin(e|es|ing)\b", r"\bquarry(ing)?\b", r"\bexcavation\b",
                  r"\bbare (soil|ground|land)\b", r"\bbarren\b"),
        task=TaskType.GROUNDING, bitemporal_task=TaskType.CHANGE_DETECTION,
        classes=("bare_soil",), indices=("BSI", "NDVI"), modalities=("optical",),
        reads_as="delineate exposed bare ground",
        priority=66,
    ),
    Event(
        key="cloud_penetration", label="All-weather radar observation",
        patterns=(r"\bthrough (the )?cloud(s)?\b", r"\ball[- ]weather\b",
                  r"\bcloud(y| cover| deck)?\b", r"\bmonsoon cloud\b", r"\bat night\b"),
        task=TaskType.OPTICAL_SAR_FUSION, bitemporal_task=TaskType.OPTICAL_SAR_FUSION,
        classes=("water",), indices=("MNDWI",), modalities=("optical", "sar"),
        reads_as="combine optical and radar so cloud does not hide the surface",
        priority=60,
    ),
    # --- phenomena this sensor suite genuinely cannot measure -------------
    Event(
        key="air_quality", label="Air quality",
        patterns=(r"\bair (quality|pollution)\b", r"\baqi\b", r"\bpm\s?2\.?5\b",
                  r"\bpm\s?10\b", r"\bsmog\b", r"\bhaze\b", r"\baerosol(s)?\b",
                  r"\bemission(s)?\b", r"\bno2\b", r"\bcarbon monoxide\b"),
        task=TaskType.CAPTION,
        classes=(), indices=(), modalities=("optical",),
        reads_as="describe the surface conditions visible over the area",
        unsupported=(
            "Air quality is an atmospheric-composition measurement. The layers this "
            "system queries (MODIS/VIIRS surface reflectance and Sentinel-1 radar) "
            "observe the ground, not trace gases or aerosol loading, so no air-quality "
            "figure is reported. What follows is the surface observation for the same "
            "area and date; Sentinel-5P TROPOMI would be the right instrument for the "
            "atmospheric question."),
        priority=99,
    ),
    Event(
        key="temperature", label="Surface temperature",
        patterns=(r"\btemperature\b", r"\bheat ?wave\b", r"\bheat island\b",
                  r"\bthermal\b", r"\bhow hot\b"),
        task=TaskType.CAPTION,
        classes=(), indices=("NDBI", "NDVI"), modalities=("optical",),
        reads_as="describe the surface cover that drives local heating",
        unsupported=(
            "Land-surface temperature needs a thermal-infrared band. The layers this "
            "system queries carry visible, near-infrared and shortwave-infrared "
            "reflectance plus radar backscatter, so no temperature value is reported. "
            "The built-up and vegetation measurements below are the surface properties "
            "that drive local heating, and MODIS LST would be the right product for "
            "the temperature itself."),
        priority=97,
    ),
)


# --------------------------------------------------------------------------
# Analytical verbs, for queries that name an action but no event
# --------------------------------------------------------------------------
_ACTION_PATTERNS: tuple[tuple[TaskType, str, str], ...] = (
    (TaskType.CHANGE_DETECTION, r"\bchange(s|d)?\b|\bcompare\b|\bbefore and after\b|"
                                r"\bversus\b|\bvs\.?\b|\bdifference\b|\bgrowth\b|"
                                r"\bloss\b|\bgain\b|\bincrease(d)?\b|\bdecrease(d)?\b",
     "compare two dates"),
    (TaskType.TIME_SERIES, r"\btrend(s)?\b|\btime series\b|\bover the (years|months)\b|"
                           r"\bseasonal\b|\bmonthly\b|\byearly\b|\bevolution\b|"
                           r"\bhistory\b",
     "build a time series"),
    (TaskType.GROUNDING, r"\bwhere\b|\blocate\b|\bhighlight\b|\bmark\b|\bdelineate\b|"
                         r"\bextent\b|\bmap\b|\bmapping\b|\bfind\b",
     "locate and outline the target on the map"),
    (TaskType.LANDCOVER, r"\bland ?cover\b|\bland ?use\b|\bclassif(y|ication)\b|"
                         r"\bbreak ?down\b|\bcomposition\b",
     "classify land cover"),
)


@dataclass
class Interpretation:
    """What a short query was understood to mean."""

    normalised: str
    event: Event | None = None
    task: TaskType | None = None
    classes: list[str] = field(default_factory=list)
    indices: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=list)
    action_note: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def unsupported(self) -> str | None:
        return self.event.unsupported if self.event else None

    @property
    def event_label(self) -> str | None:
        return self.event.label if self.event else None


def detect_event(query: str) -> Event | None:
    """The highest-priority phenomenon named in the query, if any."""
    text = normalise(query).lower()
    hits = [e for e in EVENTS if any(re.search(p, text) for p in e.patterns)]
    if not hits:
        return None
    return max(hits, key=lambda e: e.priority)


def interpret(query: str, date_count: int = 0) -> Interpretation:
    """Read a query - short or long - for its phenomenon and requested action.

    ``date_count`` is how many dates the date extractor found. Two dates turn
    most hazard questions into a bi-temporal comparison, which is both what the
    user meant and the more informative analysis.
    """
    text = normalise(query)
    low = text.lower()
    out = Interpretation(normalised=text)

    event = detect_event(text)
    if event is not None:
        out.event = event
        out.classes = list(event.classes)
        out.indices = list(event.indices)
        out.modalities = list(event.modalities)
        out.task = event.task
        if date_count >= 2 and event.bitemporal_task is not None:
            out.task = event.bitemporal_task
            out.notes.append(
                f"two dates given, so '{event.label}' is analysed as a comparison")
        out.notes.append(f"recognised phenomenon '{event.label}' -> {event.reads_as}")

    # An explicit action verb overrides the event's default task: "Kerala flood
    # trend" is a time series about floods, not a single-date flood map.
    for task, pattern, note in _ACTION_PATTERNS:
        if re.search(pattern, low):
            # Grounding is the weakest of these signals ("map", "find"), so it
            # must not displace a comparison the event already established.
            if task is TaskType.GROUNDING and out.task in (
                    TaskType.CHANGE_DETECTION, TaskType.TIME_SERIES):
                continue
            out.task = task
            out.action_note = note
            out.notes.append(f"requested action: {note}")
            break

    return out


# --------------------------------------------------------------------------
# Restating the query back to the user
# --------------------------------------------------------------------------
_TASK_PHRASE: dict[str, str] = {
    "vqa": "answer a question about",
    "caption": "describe",
    "grounding": "locate and outline features in",
    "change_detection": "detect what changed in",
    "change_vqa": "quantify the change in",
    "optical_sar_fusion": "combine optical and radar imagery over",
    "landcover": "classify the land cover of",
    "index_analysis": "compute spectral indices over",
    "time_series": "build a time series over",
    "unsupported": "process",
}


def restate(task: TaskType, aoi_name: str | None, dates: list[str],
            event: Event | None, indices: list[str],
            on_upload: bool = False) -> str:
    """One plain sentence: what the system took the question to mean.

    Every clause comes from a field that was actually resolved - if no place
    was found the sentence says so rather than naming one.
    """
    verb = _TASK_PHRASE.get(task.value, "analyse")
    if on_upload:
        # Naming the upload twice ("analyse your uploaded imagery to describe
        # your uploaded image") reads as a stutter, so it is named once.
        parts = [f"Analyse the image you uploaded to {verb} it"]
    else:
        where = aoi_name or "an area that still needs to be named"
        parts = [f"Analyse satellite imagery to {verb} {where}"]

    if event is not None:
        parts.append(f", focusing on {event.label.lower()}")
    if dates:
        if len(dates) == 1:
            parts.append(f", observed around {dates[0]}")
        else:
            parts.append(f", comparing {dates[0]} with {dates[-1]}")
    if indices:
        parts.append(f", using {', '.join(indices)}")
    return "".join(parts) + "."
