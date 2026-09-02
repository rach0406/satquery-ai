"""Place-name to bounding-box resolution.

A small offline gazetteer covers the areas we demo (so a live SIH demo never
depends on a geocoding service), and an optional OpenStreetMap Nominatim
lookup extends coverage to anywhere on Earth when the network is available.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import requests

from ..config import settings


@dataclass(frozen=True)
class Place:
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    kind: str = "city"
    country: str = "India"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    note: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        w, s, e, n = self.bbox
        return ((w + e) / 2.0, (s + n) / 2.0)


# --------------------------------------------------------------------------
# Offline gazetteer. Boxes are deliberately generous (0.3-1.0 deg) so a
# 512 px WMS request lands at a sensible analysis scale.
# --------------------------------------------------------------------------
_PLACES: tuple[Place, ...] = (
    # --- Indian cities / metros -------------------------------------------
    Place("Chennai", (79.95, 12.75, 80.45, 13.35), aliases=("madras",),
          note="Sentinel-1 ascending coverage every 12 days"),
    Place("Kolkata", (88.00, 22.30, 88.70, 22.95), aliases=("calcutta",)),
    Place("Mumbai", (72.60, 18.80, 73.20, 19.40), aliases=("bombay",)),
    Place("Delhi", (76.95, 28.35, 77.55, 28.95), aliases=("new delhi", "ncr")),
    Place("Bengaluru", (77.35, 12.75, 77.85, 13.20), aliases=("bangalore",)),
    Place("Hyderabad", (78.20, 17.20, 78.75, 17.65)),
    Place("Ahmedabad", (72.35, 22.85, 72.90, 23.30)),
    Place("Pune", (73.60, 18.35, 74.05, 18.75)),
    Place("Jaipur", (75.55, 26.65, 76.05, 27.05)),
    Place("Lucknow", (80.65, 26.65, 81.15, 27.05)),
    Place("Kochi", (76.10, 9.75, 76.55, 10.15), aliases=("cochin", "ernakulam")),
    Place("Visakhapatnam", (83.10, 17.55, 83.55, 17.95), aliases=("vizag",)),
    Place("Surat", (72.60, 21.00, 73.05, 21.40)),
    Place("Bhubaneswar", (85.65, 20.10, 86.05, 20.50)),
    Place("Guwahati", (91.50, 26.00, 91.95, 26.30)),
    Place("Patna", (85.00, 25.45, 85.40, 25.75)),
    Place("Srinagar", (74.65, 33.95, 75.05, 34.25)),
    Place("Dehradun", (77.85, 30.20, 78.20, 30.45)),

    # --- Indian water bodies / basins / hazard AOIs -----------------------
    Place("Chilika Lake", (85.00, 19.40, 85.75, 19.95), kind="waterbody",
          aliases=("chilka", "chilika")),
    Place("Vembanad Lake", (76.20, 9.45, 76.55, 10.20), kind="waterbody",
          aliases=("vembanad",)),
    Place("Pulicat Lake", (80.02, 13.35, 80.35, 13.75), kind="waterbody",
          aliases=("pulicat",)),
    Place("Sambhar Lake", (74.85, 26.85, 75.30, 27.15), kind="waterbody",
          aliases=("sambhar",)),
    Place("Sundarbans", (88.30, 21.50, 89.30, 22.40), kind="forest",
          aliases=("sunderbans", "sundarban")),
    Place("Kaziranga", (92.90, 26.50, 93.50, 26.80), kind="forest"),
    Place("Western Ghats", (74.00, 12.00, 76.00, 15.00), kind="region",
          aliases=("sahyadri",)),
    Place("Brahmaputra Basin", (90.50, 25.80, 92.50, 26.90), kind="basin",
          aliases=("brahmaputra",)),
    Place("Kosi Basin", (86.50, 25.30, 87.40, 26.40), kind="basin",
          aliases=("kosi", "koshi")),
    Place("Godavari Delta", (81.50, 16.20, 82.40, 17.00), kind="delta",
          aliases=("godavari",)),
    Place("Rann of Kutch", (69.00, 23.20, 71.50, 24.60), kind="region",
          aliases=("kutch", "kachchh", "rann")),
    Place("Thar Desert", (70.50, 26.00, 73.00, 28.00), kind="region",
          aliases=("thar",)),
    Place("Gangotri Glacier", (78.90, 30.75, 79.30, 31.05), kind="glacier",
          aliases=("gangotri",)),
    Place("Wayanad", (75.90, 11.50, 76.35, 11.95), kind="region"),
    Place("Bay of Bengal", (80.00, 10.00, 90.00, 20.00), kind="ocean", country="-"),
    Place("Arabian Sea", (65.00, 8.00, 75.00, 20.00), kind="ocean", country="-"),

    # --- Indian states & union territories --------------------------------
    # Short searches ("Kerala floods", "floods in Assam") name a state far more
    # often than a city, and a state that resolves offline is a state that
    # cannot be mis-geocoded to a memorial, a hotel or a Wikipedia article.
    # Boxes are clipped to a demo-sized footprint around the populated core
    # rather than the full administrative extent, so a 512 px request still
    # lands at a usable analysis scale.
    Place("Kerala", (75.20, 9.20, 77.00, 11.60), kind="state",
          aliases=("keralam",), note="Western Ghats to Malabar coast"),
    Place("Tamil Nadu", (77.30, 9.80, 79.90, 12.60), kind="state",
          aliases=("tamilnadu",)),
    Place("Karnataka", (74.50, 12.40, 77.50, 15.40), kind="state"),
    Place("Andhra Pradesh", (79.20, 14.20, 82.40, 17.20), kind="state",
          aliases=("andhra",)),
    Place("Telangana", (77.50, 16.60, 80.30, 19.20), kind="state"),
    Place("Maharashtra", (73.00, 17.60, 76.50, 20.60), kind="state"),
    Place("Gujarat", (69.80, 20.90, 73.20, 23.60), kind="state"),
    Place("Rajasthan", (72.50, 25.00, 76.50, 28.00), kind="state"),
    Place("Madhya Pradesh", (76.00, 22.00, 80.00, 25.00), kind="state"),
    Place("Uttar Pradesh", (79.00, 25.60, 82.50, 28.20), kind="state"),
    Place("Uttarakhand", (78.00, 29.40, 80.20, 31.20), kind="state",
          aliases=("uttaranchal",)),
    Place("Himachal Pradesh", (76.00, 30.80, 78.50, 32.60), kind="state",
          aliases=("himachal",)),
    Place("Punjab", (74.20, 30.20, 76.60, 32.00), kind="state"),
    Place("Haryana", (75.40, 28.20, 77.40, 30.30), kind="state"),
    Place("Bihar", (84.50, 24.80, 87.50, 26.80), kind="state"),
    Place("Jharkhand", (84.00, 22.60, 87.00, 24.60), kind="state"),
    Place("Odisha", (84.20, 19.20, 87.00, 21.80), kind="state",
          aliases=("orissa",)),
    Place("West Bengal", (86.80, 22.00, 89.00, 24.50), kind="state",
          aliases=("bengal",)),
    Place("Chhattisgarh", (80.60, 19.50, 83.60, 22.50), kind="state"),
    Place("Assam", (90.60, 25.60, 94.20, 27.20), kind="state",
          note="Brahmaputra valley - annual monsoon flooding"),
    Place("Meghalaya", (90.30, 25.10, 92.70, 26.10), kind="state"),
    Place("Manipur", (93.20, 24.10, 94.60, 25.50), kind="state"),
    Place("Nagaland", (93.40, 25.30, 95.10, 26.90), kind="state"),
    Place("Tripura", (91.20, 23.00, 92.30, 24.50), kind="state"),
    Place("Mizoram", (92.30, 22.10, 93.30, 24.40), kind="state"),
    Place("Arunachal Pradesh", (92.50, 27.10, 95.80, 28.80), kind="state",
          aliases=("arunachal",)),
    Place("Sikkim", (88.00, 27.10, 88.90, 28.10), kind="state"),
    Place("Goa", (73.70, 14.90, 74.35, 15.80), kind="state"),
    Place("Jammu and Kashmir", (73.90, 32.70, 76.50, 34.60), kind="state",
          aliases=("kashmir", "jammu")),
    Place("Ladakh", (76.00, 33.50, 79.00, 35.50), kind="state"),
    Place("Puducherry", (79.65, 11.75, 79.95, 12.05), kind="state",
          aliases=("pondicherry",)),
    Place("Andaman Islands", (92.20, 10.50, 93.20, 13.60), kind="region",
          aliases=("andaman", "andaman and nicobar")),
    Place("India", (68.00, 8.00, 89.00, 30.00), kind="country", country="India",
          note="whole-country box; name a state or city for a usable scale"),

    # --- International reference AOIs (useful for cross-checks) ----------
    Place("Amazon Rainforest", (-62.00, -6.00, -58.00, -2.00), kind="forest",
          country="Brazil", aliases=("amazon",)),
    Place("Aral Sea", (58.00, 44.00, 61.50, 46.80), kind="waterbody",
          country="Uzbekistan", aliases=("aral",)),
    Place("Lake Chad", (13.00, 12.50, 15.30, 14.50), kind="waterbody",
          country="Chad"),
    Place("Dubai", (54.80, 24.90, 55.60, 25.45), country="UAE"),
    Place("California", (-122.60, 36.80, -119.50, 39.20), kind="region",
          country="USA"),
    Place("Sahara Desert", (0.00, 22.00, 6.00, 27.00), kind="region",
          country="-", aliases=("sahara",)),
    Place("Australia", (144.00, -38.00, 150.00, -32.00), kind="region",
          country="Australia", note="south-east Australia - recurrent bushfire belt"),
    Place("Amazon Basin", (-70.00, -10.00, -60.00, -2.00), kind="forest",
          country="Brazil", aliases=("amazonia", "amazon basin")),
    Place("Congo Basin", (16.00, -3.00, 22.00, 2.00), kind="forest",
          country="DR Congo", aliases=("congo",)),
    Place("Nile Delta", (30.00, 30.20, 32.20, 31.60), kind="delta",
          country="Egypt", aliases=("nile",)),
    Place("Mekong Delta", (105.20, 9.00, 107.00, 10.80), kind="delta",
          country="Vietnam", aliases=("mekong",)),
    Place("Greenland", (-50.00, 66.00, -42.00, 71.00), kind="glacier",
          country="Greenland"),
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


_INDEX: dict[str, Place] = {}
for _p in _PLACES:
    _INDEX[_norm(_p.name)] = _p
    for _a in _p.aliases:
        _INDEX[_norm(_a)] = _p


def all_places() -> list[Place]:
    return list(_PLACES)


def lookup_offline(text: str) -> Place | None:
    """Longest-match place detection inside a free-text query."""
    n = _norm(text)
    if n in _INDEX:
        return _INDEX[n]
    best: Place | None = None
    best_len = 0
    for key, place in _INDEX.items():
        # Word-boundary containment so "pune" does not match "puneet".
        if len(key) > best_len and re.search(rf"\b{re.escape(key)}\b", n):
            best, best_len = place, len(key)
    return best


#: OSM feature classes that denote an actual piece of the Earth's surface.
#:
#: Nominatim indexes far more than geography. A search for "Kerala floods"
#: returns the *2018 Kerala floods* - a `historic`/`memorial` node with a
#: 200 m bounding box - and the system would then confidently report land
#: cover for a memorial plaque while calling it Kerala. Restricting results to
#: these classes keeps the answer to places, and the event words are stripped
#: from the query before it is ever sent (see :func:`_geocodable_terms`).
_PLACE_CLASSES = frozenset({
    "boundary", "place", "natural", "landuse", "waterway", "water",
    "administrative", "region", "landform",
})

#: Rejected outright: a name carrying a year is an event article, not a place.
_EVENTISH = re.compile(r"\b(19|20)\d{2}\b|\b(flood|cyclone|earthquake|disaster|"
                       r"memorial|museum|hotel|restaurant|relief camp)s?\b", re.I)


def _acceptable_row(row: dict) -> bool:
    cls = str(row.get("class", "")).lower()
    if cls and cls not in _PLACE_CLASSES:
        return False
    name = str(row.get("display_name", ""))
    return not _EVENTISH.search(name.split(",")[0])


#: Nominatim asks for at most one request per second and the same handful of
#: place names recur constantly during a demo, so every lookup is memoised for
#: the life of the process.
_GEOCODE_CACHE: dict[str, "Place | None"] = {}


def lookup_nominatim(text: str) -> Place | None:
    """Optional online fallback. Never raises - returns None on any failure."""
    if settings.offline_mode:
        return None
    key = _norm(text)
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    result = _lookup_nominatim_uncached(text)
    _GEOCODE_CACHE[key] = result
    return result


def _lookup_nominatim_uncached(text: str) -> Place | None:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": text, "format": "json", "limit": 8, "addressdetails": 0},
            headers={"User-Agent": "SatQueryAI/1.0 (SIH26167 Avengers)"},
            timeout=min(settings.http_timeout, 12),
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = next((r for r in rows if _acceptable_row(r)), None)
        if row is None:
            # Every candidate was an event, a building or a point of interest.
            # Refusing is correct: the controller then asks which area to use.
            return None
        # Nominatim boundingbox is [south, north, west, east] as strings.
        s, n, w, e = (float(v) for v in row["boundingbox"])
        # Guarantee a minimum analysis footprint of ~0.2 deg.
        if e - w < 0.2:
            cx = (e + w) / 2
            w, e = cx - 0.1, cx + 0.1
        if n - s < 0.2:
            cy = (n + s) / 2
            s, n = cy - 0.1, cy + 0.1
        # And cap it so we never request a hemisphere.
        w, e = max(w, -180.0), min(e, 180.0)
        s, n = max(s, -85.0), min(n, 85.0)
        if e - w > 12:
            cx = (e + w) / 2
            w, e = cx - 6, cx + 6
        if n - s > 12:
            cy = (n + s) / 2
            s, n = cy - 6, cy + 6
        return Place(
            name=row.get("display_name", text).split(",")[0].strip(),
            bbox=(w, s, e, n),
            kind=row.get("type", "place"),
            country=row.get("display_name", "").split(",")[-1].strip() or "-",
            note="resolved via OpenStreetMap Nominatim",
        )
    except Exception:
        return None


#: Words that must never survive into a geocoding request.
#:
#: Nominatim will happily return a match for almost any string - there is a
#: place called "There!" and another called "Trend" - so "How much water is
#: there?" would silently resolve to a real bounding box and the system would
#: confidently report statistics for a location the user never asked about.
#: Refusing to geocode is the correct behaviour: the controller then asks which
#: area to analyse.
_STOPWORDS = frozenset("""
show me the a an in on at over near around for of from to between and or but
what which where when how why who whom whose is are was were be been being do
does did done has have had having can could will would shall should may might
must this that these those there here it its their his her our your my mine
much many more most less least any some all both each every no not none
change changed changes detect detection map mapping analyse analyze analysis
compare comparison trend trends time series recent latest current now today
yesterday last past next year years month months week weeks day days season
water flood flooding flooded inundation vegetation forest forests crop crops
cropland urban built up builtup area areas region regions land cover landcover
image images imagery scene scenes satellite sensor optical radar sar band bands
ndvi ndwi mndwi nbr ndbi bsi vari index indices pixel pixels percent percentage
increase increased decrease decreased grow grew shrink shrunk expand expanded
describe description caption highlight locate find identify give tell explain
please kindly right visible major features covered coverage during before after
cyclone cyclones hurricane typhoon storm storms surge wildfire wildfires fire
fires bushfire burnt burned burn scar drought droughts deforestation logging
landslide landslides mudslide erosion pollution smog haze aerosol quality
disaster disasters damage affected impact impacted event events extent
growth expansion sprawl construction urbanisation urbanization loss gain
melt melting retreat glacier snowmelt waterlogging inundated submerged
health yield harvest sowing status situation report summary insight insights
air quality level levels rise rising fall falling high low new old around
affected hit struck severe worst analysis analyse analyze detected detection
""".split())


def _plural_base(word: str) -> str:
    """'floods' -> 'flood', 'cities' -> 'city'. Crude, but enough for stopwords."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 4 and word[-3] in "sxzh":
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _geocodable_terms(text: str) -> str:
    """Strip everything that is not a plausible place token.

    Plural forms matter here. The stop list carries "flood", so without this
    "Kerala floods 2025" would send "floods kerala" to the geocoder - which is
    exactly the phrasing that matches a disaster article rather than the state.
    """
    cleaned = text.lower()
    # Possessives confuse the geocoder: "antarctica's" matches nothing.
    cleaned = re.sub(r"'s\b", "", cleaned)
    # Hyphens glue a stop word onto a place name ("flood-affected Kerala"), so
    # split on them instead of carrying the pair as one unrecognised token.
    cleaned = re.sub(r"[^a-z\s']+", " ", cleaned)
    words = [w.strip("'-") for w in cleaned.split()]
    kept = [w for w in words
            if len(w) >= 3
            and w not in _STOPWORDS
            and _plural_base(w) not in _STOPWORDS]
    return " ".join(kept)


def resolve(text: str, allow_online: bool = True) -> Place | None:
    """Resolve a place mentioned anywhere in *text* to a bounding box.

    Returns ``None`` when the text contains no plausible place name. That
    ``None`` is a feature: the controller turns it into a clarification
    request rather than analysing an arbitrary corner of the planet.
    """
    place = lookup_offline(text)
    if place is not None:
        return place
    if not allow_online:
        return None

    candidate = _geocodable_terms(text)
    # One short leftover token is not evidence of a place name.
    if not candidate or len(candidate) < 4:
        return None
    return lookup_nominatim(candidate)


def bbox_area_km2(bbox: tuple[float, float, float, float] | list[float]) -> float:
    """Approximate area of a lat/lon box in square kilometres."""
    import math

    w, s, e, n = bbox
    lat_mid = math.radians((s + n) / 2.0)
    dy = (n - s) * 110.574
    dx = (e - w) * 111.320 * math.cos(lat_mid)
    return abs(dx * dy)


def pixel_area_km2(bbox: list[float] | tuple[float, ...], width: int, height: int) -> float:
    return bbox_area_km2(tuple(bbox)) / float(max(width * height, 1))
