"""Natural-language understanding: query -> :class:`QueryPlan`.

Two parsers produce the *same* validated structure:

* **rules** - a deterministic gazetteer/keyword/date parser. Always available,
  needs no network, no key and no GPU. This is what runs during the demo if
  anything else fails, and it is what makes the pipeline reproducible.
* **llm** - optional Claude call using strict tool/function calling, so the
  model returns a typed plan rather than prose. Used to widen coverage of
  unusual phrasings.

When both run, the LLM plan is *merged over* the rule plan and every field the
LLM supplies is re-validated (place resolvable, dates parseable and in range,
index known). Anything that fails validation falls back to the rule value.
The LLM never touches measurements - only the plan.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..config import settings
from ..datasources import gazetteer
from ..processing.indices import INDEX_REQUIREMENTS
from ..schemas import InputConfiguration, QueryPlan, TaskType
from . import intent

# --------------------------------------------------------------------------
# Keyword tables
# --------------------------------------------------------------------------
TASK_PATTERNS: list[tuple[TaskType, tuple[str, ...], int]] = [
    (TaskType.OPTICAL_SAR_FUSION, (
        r"\boptical\b.{0,40}\bsar\b", r"\bsar\b.{0,40}\boptical\b",
        r"\bboth\s+(sensors|modalities|images)\b", r"\bfus(e|ion|ing)\b",
        r"\bcross[- ]?modal\b", r"\bradar\b.{0,40}\boptical\b",
        r"\bcombine\b.{0,30}\b(radar|sar)\b", r"\bsee through (the )?cloud",
    ), 100),
    (TaskType.CHANGE_VQA, (
        r"\bhas\b.{0,40}\b(increased|decreased|changed|grown|shrunk|expanded)\b",
        r"\b(increase|decrease)d?\b.{0,20}\bor\b.{0,20}\b(increase|decrease)d?\b",
        r"\bhow much\b.{0,40}\b(change|changed|grow|grew|lost|gained)\b",
        r"\bdid\b.{0,40}\b(change|shrink|expand|grow)\b",
    ), 95),
    (TaskType.CHANGE_DETECTION, (
        r"\bchange detection\b", r"\bwhat changed\b", r"\bchanges?\b.{0,30}\bbetween\b",
        r"\bbetween\b.{0,40}\band\b.{0,30}\b(20\d\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        r"\bbefore\b.{0,30}\bafter\b", r"\bcompare\b", r"\bbi-?temporal\b",
        r"\bover time\b", r"\bsince\b\s+20\d\d", r"\bdifference\b.{0,30}\bbetween\b",
    ), 90),
    (TaskType.GROUNDING, (
        r"\bhighlight\b", r"\blocate\b", r"\bwhere (is|are)\b", r"\bshow me where\b",
        r"\bmark\b.{0,25}\b(the|all)\b", r"\bdelineate\b", r"\bpinpoint\b",
        r"\bfind\b.{0,25}\b(the|all)\b.{0,25}\b(water|lake|river|forest|urban|built)",
        r"\bwhere did\b.{0,30}\boccur\b",
    ), 85),
    (TaskType.TIME_SERIES, (
        r"\btime series\b", r"\btrend\b", r"\bover the (last|past)\b.{0,20}\b(year|month|week)",
        r"\bmonth(ly)? (average|mean)\b", r"\bseasonal\b", r"\bevolution\b",
    ), 80),
    (TaskType.CAPTION, (
        r"\bdescribe\b", r"\bcaption\b", r"\bwhat (do you |can you )?(see|is visible)\b",
        r"\bsummar(ise|ize)\b.{0,25}\b(scene|image)\b", r"\bwhat is (in|shown in) this\b",
        r"\boverview of\b",
    ), 70),
    (TaskType.LANDCOVER, (
        r"\bland ?cover\b", r"\bland ?use\b", r"\bclassif(y|ication)\b",
        r"\bwhat classes\b", r"\bbreak ?down\b",
    ), 65),
    (TaskType.INDEX_ANALYSIS, (
        r"\bndvi\b", r"\bndwi\b", r"\bmndwi\b", r"\bnbr\b", r"\bndbi\b", r"\bbsi\b", r"\bvari\b",
        r"\bvegetation index\b", r"\bburn (ratio|index|severity)\b", r"\bwater index\b",
    ), 60),
]

CLASS_SYNONYMS: dict[str, tuple[str, ...]] = {
    "water": ("water", "water body", "waterbody", "waterbodies", "water bodies",
              "lake", "lakes", "river", "rivers", "reservoir", "reservoirs", "sea",
              "ocean", "flood", "floods", "flooded", "flooding", "inundation",
              "inundated", "wetland", "wetlands", "lagoon", "backwater", "backwaters",
              "pond", "ponds", "canal", "canals", "estuary", "waterlogging",
              "submerged", "deluge"),
    "dense_vegetation": ("forest", "forests", "forested", "jungle", "canopy", "tree cover",
                         "trees", "woodland", "mangrove", "mangroves", "plantation",
                         "plantations", "dense vegetation", "deforestation", "rainforest"),
    "sparse_vegetation": ("crop", "crops", "cropland", "farmland", "agriculture",
                          "agricultural", "field", "fields", "pasture", "grassland",
                          "vegetation", "green cover", "greenery", "sparse vegetation",
                          "farms", "harvest", "kharif", "rabi", "irrigation"),
    "built_up": ("built up", "built-up", "builtup", "urban", "urbanisation",
                 "urbanization", "city", "cities", "settlement", "settlements",
                 "residential", "industrial", "impervious", "construction",
                 "infrastructure", "buildings", "town", "towns", "sprawl"),
    "bare_soil": ("bare soil", "bare", "soil", "barren", "desert", "sand", "exposed",
                  "mine", "mines", "mining", "quarry"),
    "cloud_or_snow": ("cloud", "clouds", "cloudy", "snow", "ice", "glacier", "glaciers",
                      "snowmelt", "snow cover"),
}

INDEX_SYNONYMS: dict[str, tuple[str, ...]] = {
    "NDVI": ("ndvi", "vegetation index", "greenness", "vegetation health", "vegetation vigour"),
    "MNDWI": ("mndwi", "modified water index"),
    "NDWI": ("ndwi", "water index"),
    "NBR": ("nbr", "burn ratio", "burn severity", "fire severity", "burnt", "burned"),
    "NDBI": ("ndbi", "built-up index", "builtup index", "urban index"),
    "BSI": ("bsi", "bare soil index"),
    "VARI": ("vari",),
}

MODALITY_HINTS: dict[str, tuple[str, ...]] = {
    "sar": ("sar", "radar", "sentinel-1", "sentinel 1", "s1", "backscatter", "risat",
            "microwave", "all-weather", "through cloud", "night"),
    "optical": ("optical", "true colour", "true color", "rgb", "visible", "modis",
                "viirs", "sentinel-2", "sentinel 2", "multispectral", "reflectance"),
}

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

SEASONS = {
    "monsoon": (6, 9), "southwest monsoon": (6, 9), "northeast monsoon": (10, 12),
    "summer": (3, 5), "winter": (12, 2), "post-monsoon": (10, 11),
    "pre-monsoon": (3, 5), "kharif": (6, 10), "rabi": (11, 3),
}


# --------------------------------------------------------------------------
# Date extraction
# --------------------------------------------------------------------------
@dataclass
class DateHit:
    iso: str
    text: str
    precision: str   # day | month | year | season


def _clamp(d: date) -> date:
    """Never ask an archive for tomorrow; leave latency for processing."""
    latest = date.today() - timedelta(days=2)
    return min(d, latest)


def _mid_month(y: int, m: int) -> date:
    return date(y, m, 15)


def extract_dates(text: str, today: date | None = None) -> list[DateHit]:
    t = text.lower()
    today = today or date.today()
    hits: list[DateHit] = []

    # ISO first - unambiguous.
    for m in re.finditer(r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b", t):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            hits.append(DateHit(_clamp(d).isoformat(), m.group(0), "day"))
        except ValueError:
            pass

    # "15 March 2024" / "March 15, 2024" / "March 2024"
    month_re = "|".join(sorted(MONTHS, key=len, reverse=True))
    for m in re.finditer(rf"\b(\d{{1,2}})\s+({month_re})\.?\s+((?:19|20)\d{{2}})\b", t):
        try:
            d = date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
            hits.append(DateHit(_clamp(d).isoformat(), m.group(0), "day"))
        except ValueError:
            pass
    for m in re.finditer(rf"\b({month_re})\.?\s+(\d{{1,2}}),?\s+((?:19|20)\d{{2}})\b", t):
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
            hits.append(DateHit(_clamp(d).isoformat(), m.group(0), "day"))
        except ValueError:
            pass
    for m in re.finditer(rf"\b({month_re})\.?\s+((?:19|20)\d{{2}})\b", t):
        if any(m.group(0) in h.text for h in hits):
            continue
        d = _mid_month(int(m.group(2)), MONTHS[m.group(1)])
        hits.append(DateHit(_clamp(d).isoformat(), m.group(0), "month"))

    # A bare month that shares the year stated later in the sentence:
    # "between January and October 2025" names two moments, not one, and a
    # change query that only sees October has lost half the question.
    years_seen = sorted({int(h.iso[:4]) for h in hits})
    if years_seen:
        year = years_seen[-1]
        for m in re.finditer(rf"\b({month_re})\.?\b(?!\s*\.?\s*(?:\d{{1,2}},?\s*)?(?:19|20)\d{{2}})",
                             t):
            mon = MONTHS[m.group(1)]
            d = _mid_month(year, mon)
            iso = _clamp(d).isoformat()
            if not any(h.iso[:7] == iso[:7] for h in hits):
                hits.append(DateHit(iso, f"{m.group(0)} (year {year} from context)", "month"))

    # Season + year, e.g. "monsoon 2024".
    for name, (m0, m1) in SEASONS.items():
        for m in re.finditer(rf"\b{re.escape(name)}\s+(?:of\s+)?((?:19|20)\d{{2}})\b", t):
            y = int(m.group(1))
            mid = m0 if m1 >= m0 else 1
            mid = (m0 + m1) // 2 if m1 >= m0 else 1
            hits.append(DateHit(_clamp(_mid_month(y, max(1, min(12, mid)))).isoformat(),
                                m.group(0), "season"))

    # Bare years, only if nothing more precise already covers them.
    # 19xx is matched deliberately. A pre-2000 year is not noise to be ignored:
    # it is a request the archive cannot satisfy, and the validator has to see
    # it in order to say so instead of quietly analysing today instead.
    for m in re.finditer(r"\b((?:19|20)\d{2})\b", t):
        y = int(m.group(1))
        if any(h.iso.startswith(str(y)) for h in hits):
            continue
        if y > today.year:
            continue
        d = date(y, 6, 15) if y < today.year else _clamp(today - timedelta(days=30))
        hits.append(DateHit(_clamp(d).isoformat(), m.group(0), "year"))

    # Relative expressions.
    rel = [
        (r"\blast month\b", 30), (r"\bpast month\b", 30), (r"\blast week\b", 7),
        (r"\byesterday\b", 1), (r"\btoday\b", 0), (r"\blast year\b", 365),
        (r"\ba year ago\b", 365), (r"\bsix months ago\b", 182),
        (r"\brecent(ly)?\b", 10), (r"\bnow\b", 0), (r"\bcurrent(ly)?\b", 0),
        (r"\blatest\b", 5),
    ]
    for pat, days in rel:
        if re.search(pat, t):
            hits.append(DateHit(_clamp(today - timedelta(days=days)).isoformat(), pat, "day"))

    for m in re.finditer(r"\b(\d{1,2})\s+(year|month|week|day)s?\s+ago\b", t):
        n = int(m.group(1))
        mult = {"year": 365, "month": 30, "week": 7, "day": 1}[m.group(2)]
        hits.append(DateHit(_clamp(today - timedelta(days=n * mult)).isoformat(), m.group(0), "day"))

    seen: set[str] = set()
    out: list[DateHit] = []
    for h in sorted(hits, key=lambda x: x.iso):
        if h.iso not in seen:
            seen.add(h.iso)
            out.append(h)
    return out


# --------------------------------------------------------------------------
# Rule parser
# --------------------------------------------------------------------------
def _match_task(text: str) -> tuple[TaskType, float, list[str]]:
    t = text.lower()
    scored: list[tuple[int, TaskType, str]] = []
    for task, pats, weight in TASK_PATTERNS:
        for p in pats:
            if re.search(p, t):
                scored.append((weight, task, p))
                break
    if not scored:
        # A question mark or an interrogative word with no other signal is VQA.
        if "?" in text or re.match(r"^\s*(what|how|is|are|does|do|which|can|has|have|why|when)\b", t):
            return TaskType.VQA, 0.55, ["defaulted to VQA from interrogative form"]
        return TaskType.CAPTION, 0.4, ["no task keyword matched; defaulted to scene description"]

    scored.sort(key=lambda s: -s[0])
    best = scored[0]
    notes = [f"matched /{best[2]}/ -> {best[1].value}"]
    conf = 0.6 + min(len(scored), 3) * 0.08
    if len(scored) > 1 and scored[1][0] == best[0]:
        conf -= 0.1
        notes.append(f"ambiguous with {scored[1][1].value}")
    return best[1], min(conf, 0.92), notes


def _match_classes(text: str) -> list[str]:
    t = f" {text.lower()} "
    found: list[str] = []
    for cls, syns in CLASS_SYNONYMS.items():
        for s in syns:
            if re.search(rf"\b{re.escape(s)}\b", t):
                found.append(cls)
                break
    return found


def _match_indices(text: str, classes: list[str]) -> list[str]:
    t = text.lower()
    found: list[str] = []
    for idx, syns in INDEX_SYNONYMS.items():
        for s in syns:
            if re.search(rf"\b{re.escape(s)}\b", t):
                found.append(idx)
                break
    if not found:
        # Infer a sensible index from the subject matter.
        mapping = {"water": "MNDWI", "dense_vegetation": "NDVI",
                   "sparse_vegetation": "NDVI", "built_up": "NDBI", "bare_soil": "BSI"}
        for c in classes:
            if c in mapping and mapping[c] not in found:
                found.append(mapping[c])
    return [f for f in found if f in INDEX_REQUIREMENTS]


def _match_modalities(text: str) -> list[str]:
    t = text.lower()
    out: list[str] = []
    for mod, hints in MODALITY_HINTS.items():
        if any(re.search(rf"\b{re.escape(h)}\b", t) for h in hints):
            out.append(mod)
    return out


def parse_rules(query: str, allow_online_geocode: bool = True) -> QueryPlan:
    task, conf, notes = _match_task(query)
    classes = _match_classes(query)
    indices = _match_indices(query, classes)
    modalities = _match_modalities(query)
    dates = [h.iso for h in extract_dates(query)]

    # ---- short-query interpretation --------------------------------------
    # The sentence patterns above only fire on a written question. A search-box
    # query ("Kerala floods 2025") reaches here classified as a generic scene
    # description with nothing to look for, so the event lexicon supplies the
    # domain reading. It only fills what the sentence parser left empty, and
    # the phenomenon it recognises is a *choice of analysis*, never a claim
    # that the phenomenon occurred.
    reading = intent.interpret(query, date_count=len(dates))
    unsupported_note: str | None = reading.unsupported

    if reading.task is not None:
        weak_task = task in (TaskType.CAPTION, TaskType.VQA) and conf < 0.62
        if weak_task or intent.is_short_query(query):
            if task is not reading.task:
                notes.append(
                    f"short-query interpretation: {task.value} -> {reading.task.value}")
            task = reading.task
            conf = max(conf, 0.68)
    for c in reading.classes:
        if c not in classes:
            classes.append(c)
    if not indices:
        indices = [i for i in reading.indices if i in INDEX_REQUIREMENTS]
    for m in reading.modalities:
        if m not in modalities and m in ("optical", "sar"):
            modalities.append(m)
    notes.extend(reading.notes)

    place = gazetteer.resolve(query, allow_online=allow_online_geocode)
    ambiguities: list[str] = []

    if place is None:
        ambiguities.append("no_location")
    if not dates:
        ambiguities.append("no_date")

    # Task/date consistency: change analysis needs two dates.
    if task in (TaskType.CHANGE_DETECTION, TaskType.CHANGE_VQA):
        config = InputConfiguration.BITEMPORAL
        if len(dates) < 2:
            ambiguities.append("change_needs_two_dates")
    elif task is TaskType.OPTICAL_SAR_FUSION:
        config = InputConfiguration.CROSS_MODAL
        if "sar" not in modalities:
            modalities.append("sar")
        if "optical" not in modalities:
            modalities.append("optical")
    elif task is TaskType.TIME_SERIES:
        config = InputConfiguration.NONE
    else:
        config = InputConfiguration.SINGLE

    if place is not None:
        notes.append(f"resolved AOI '{place.name}' -> {[round(v, 3) for v in place.bbox]}")
        conf += 0.05
    if dates:
        notes.append(f"extracted dates {dates}")
        conf += 0.03
    if unsupported_note:
        ambiguities.append("out_of_scope_quantity")
        notes.append("requested quantity is outside this sensor suite; "
                     "the observable surface analysis is run instead")

    return QueryPlan(
        raw_query=query,
        task=task,
        input_configuration=config,
        aoi_name=place.name if place else None,
        bbox=list(place.bbox) if place else None,
        dates=dates,
        target_classes=classes,
        indices=indices,
        modalities=modalities,
        parser="rules",
        confidence=round(min(conf, 0.95), 3),
        ambiguities=ambiguities,
        notes=notes,
        interpretation=intent.restate(task, place.name if place else None, dates,
                                      reading.event, indices),
        event=reading.event_label,
        unsupported_aspect=unsupported_note,
        normalised_query=reading.normalised,
    )


# --------------------------------------------------------------------------
# LLM parser (optional)
# --------------------------------------------------------------------------
PLAN_TOOL = {
    "name": "emit_query_plan",
    "description": (
        "Emit the structured analysis plan for a remote-sensing question. "
        "You are a parser only: extract intent and parameters. Never invent "
        "measurements, statistics or observations - you have not seen any imagery."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "enum": [t.value for t in TaskType if t is not TaskType.UNSUPPORTED],
                "description": (
                    "vqa: a specific factual question about one scene. "
                    "caption: describe/summarise a scene. "
                    "grounding: locate or highlight something spatially. "
                    "change_detection: what changed between two dates. "
                    "change_vqa: a yes/no or magnitude question about change. "
                    "optical_sar_fusion: use optical AND SAR together. "
                    "landcover: land-cover/land-use breakdown. "
                    "index_analysis: a named spectral index. "
                    "time_series: a trend over many dates."
                ),
            },
            "location": {"type": "string", "description": "Place name exactly as written, or empty."},
            "dates": {
                "type": "array", "items": {"type": "string"},
                "description": "ISO YYYY-MM-DD dates implied by the query, earliest first.",
            },
            "target_classes": {
                "type": "array",
                "items": {"type": "string", "enum": list(CLASS_SYNONYMS.keys())},
            },
            "indices": {
                "type": "array",
                "items": {"type": "string", "enum": list(INDEX_REQUIREMENTS.keys())},
            },
            "modalities": {
                "type": "array", "items": {"type": "string", "enum": ["optical", "sar"]},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "ambiguities": {
                "type": "array", "items": {"type": "string"},
                "description": "Anything genuinely unclear that would change the analysis.",
            },
        },
        "required": ["task", "confidence"],
    },
}

LLM_SYSTEM = (
    "You convert natural-language remote-sensing questions into a structured plan.\n"
    "Rules:\n"
    "1. You are a PARSER. You have not seen any satellite image. Never output "
    "measurements, percentages, areas or observations.\n"
    "2. Call emit_query_plan exactly once.\n"
    "3. Resolve relative dates against today's date, given below.\n"
    "4. If the question compares two moments in time, emit two dates.\n"
    "5. Leave a field empty rather than guessing.\n"
)


def parse_llm(query: str, today: date | None = None) -> QueryPlan | None:
    """Ask Claude for a typed plan. Returns None if unavailable or malformed."""
    if not settings.llm_available:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    today = today or date.today()
    try:
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=float(settings.llm_timeout)
        )
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=1024,
            system=LLM_SYSTEM + f"\nToday's date is {today.isoformat()}.",
            tools=[PLAN_TOOL],
            tool_choice={"type": "tool", "name": "emit_query_plan"},
            messages=[{"role": "user", "content": query}],
        )
        payload = None
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                payload = block.input
                break
        if not payload:
            return None
    except Exception:
        return None

    try:
        task = TaskType(payload.get("task", "vqa"))
    except ValueError:
        task = TaskType.VQA

    place = None
    loc = (payload.get("location") or "").strip()
    if loc:
        place = gazetteer.resolve(loc, allow_online=True)

    dates: list[str] = []
    for d in payload.get("dates", []) or []:
        try:
            dates.append(_clamp(date.fromisoformat(str(d)[:10])).isoformat())
        except ValueError:
            continue
    dates = sorted(dict.fromkeys(dates))

    config = {
        TaskType.CHANGE_DETECTION: InputConfiguration.BITEMPORAL,
        TaskType.CHANGE_VQA: InputConfiguration.BITEMPORAL,
        TaskType.OPTICAL_SAR_FUSION: InputConfiguration.CROSS_MODAL,
        TaskType.TIME_SERIES: InputConfiguration.NONE,
    }.get(task, InputConfiguration.SINGLE)

    return QueryPlan(
        raw_query=query,
        task=task,
        input_configuration=config,
        aoi_name=place.name if place else (loc or None),
        bbox=list(place.bbox) if place else None,
        dates=dates,
        target_classes=[c for c in (payload.get("target_classes") or []) if c in CLASS_SYNONYMS],
        indices=[i for i in (payload.get("indices") or []) if i in INDEX_REQUIREMENTS],
        modalities=[m for m in (payload.get("modalities") or []) if m in ("optical", "sar")],
        parser="llm",
        confidence=float(payload.get("confidence", 0.7)),
        ambiguities=list(payload.get("ambiguities") or []),
        notes=[f"LLM parser ({settings.llm_model}) returned a typed plan via tool call"],
    )


def merge_plans(rules: QueryPlan, llm: QueryPlan | None) -> QueryPlan:
    """Prefer LLM structure, but keep every rule-derived value it left empty."""
    if llm is None:
        return rules

    merged = rules.model_copy(deep=True)
    merged.parser = "hybrid"
    merged.task = llm.task
    merged.input_configuration = llm.input_configuration

    if llm.bbox:
        merged.bbox, merged.aoi_name = llm.bbox, llm.aoi_name
    elif rules.bbox:
        merged.notes.append(
            f"LLM did not resolve a location; kept rule-parsed AOI '{rules.aoi_name}'"
        )

    if llm.dates:
        merged.dates = llm.dates
    if llm.target_classes:
        merged.target_classes = llm.target_classes
    if llm.indices:
        merged.indices = llm.indices
    if llm.modalities:
        merged.modalities = llm.modalities

    if merged.task != rules.task:
        merged.notes.append(
            f"LLM overrode rule task {rules.task.value} -> {merged.task.value}"
        )
    merged.confidence = round(min(0.97, (rules.confidence + llm.confidence) / 2 + 0.08), 3)
    merged.ambiguities = sorted(set(rules.ambiguities) | set(llm.ambiguities))
    merged.notes += llm.notes
    # The restatement is derived, so it has to be rebuilt from the merged
    # fields rather than inherited from either parser.
    merged.interpretation = intent.restate(
        merged.task, merged.aoi_name, merged.dates,
        intent.detect_event(merged.raw_query), merged.indices)
    return merged


def parse(query: str, use_llm: bool | None = None) -> QueryPlan:
    """Public entry point. Rules always run; the LLM refines when available."""
    rules = parse_rules(query)
    want_llm = settings.llm_available if use_llm is None else (use_llm and settings.llm_available)
    if not want_llm:
        return rules
    return merge_plans(rules, parse_llm(query))
