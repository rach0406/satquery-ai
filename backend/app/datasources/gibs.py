"""NASA GIBS client - the project's primary source of *real* satellite pixels.

GIBS (Global Imagery Browse Services) serves NASA's operational imagery
archive over open WMS/WMTS with **no credentials**, which makes it the right
backbone for a live hackathon demo: nothing to expire, nothing to rate-limit
us out of the room.

What we pull:

======================  =========================================  ===========
composite               band mapping (R, G, B)                     use
======================  =========================================  ===========
TrueColor               B1 red, B4 green, B3 blue                   visual, RGB indices
Bands721                B7 SWIR2, B2 NIR, B1 red                    NDVI, NBR
OPERA RTC S1            gamma0 backscatter (VV/VH composite)        SAR structure
======================  =========================================  ===========

Because TrueColor and Bands721 are rendered by GIBS onto the *same* EPSG:4326
grid for the same BBOX/WIDTH/HEIGHT, the two requests come back pixel-aligned.
Stacking them yields a real 5-band multispectral cube (blue, green, red, NIR,
SWIR2) without touching a single credential-gated archive.

Honesty note carried in every Provenance record: GIBS Corrected Reflectance is
byte-scaled with a non-linear stretch for visualisation, so indices derived
from it are *indicative* rather than calibrated surface-reflectance values.
The absolute numbers are real measurements of the served product; they are not
Level-2 surface reflectance.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import io
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import requests
from PIL import Image

from ..config import settings
from ..schemas import DataOrigin, Provenance

Image.MAX_IMAGE_PIXELS = 200_000_000


# --------------------------------------------------------------------------
# Layer catalogue
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class GibsLayer:
    id: str
    title: str
    modality: str                      # optical | multispectral | sar | thermal | derived
    platform: str
    instrument: str
    resolution_m: float
    bands: tuple[str, ...]             # semantic meaning of R, G, B channels
    cadence_days: int = 1
    start: str = "2000-02-24"
    description: str = ""
    colorised: bool = False            # True => palette image, not band data


LAYERS: dict[str, GibsLayer] = {
    "modis_terra_truecolor": GibsLayer(
        id="MODIS_Terra_CorrectedReflectance_TrueColor",
        title="MODIS Terra True Colour (B1/B4/B3)",
        modality="optical", platform="Terra", instrument="MODIS",
        resolution_m=250, bands=("red", "green", "blue"),
        description="Corrected reflectance true-colour composite, daily, 250 m.",
    ),
    "modis_terra_721": GibsLayer(
        id="MODIS_Terra_CorrectedReflectance_Bands721",
        title="MODIS Terra SWIR/NIR/Red (B7/B2/B1)",
        modality="multispectral", platform="Terra", instrument="MODIS",
        resolution_m=250, bands=("swir2", "nir", "red"),
        description="Corrected reflectance 7-2-1 composite: burn scars, flood water, snow/ice.",
    ),
    "modis_aqua_truecolor": GibsLayer(
        id="MODIS_Aqua_CorrectedReflectance_TrueColor",
        title="MODIS Aqua True Colour (B1/B4/B3)",
        modality="optical", platform="Aqua", instrument="MODIS",
        resolution_m=250, bands=("red", "green", "blue"),
        start="2002-07-04",
        description="Afternoon overpass true-colour composite.",
    ),
    "modis_aqua_721": GibsLayer(
        id="MODIS_Aqua_CorrectedReflectance_Bands721",
        title="MODIS Aqua SWIR/NIR/Red (B7/B2/B1)",
        modality="multispectral", platform="Aqua", instrument="MODIS",
        resolution_m=250, bands=("swir2", "nir", "red"), start="2002-07-04",
        description="Afternoon overpass 7-2-1 composite.",
    ),
    "viirs_snpp_truecolor": GibsLayer(
        id="VIIRS_SNPP_CorrectedReflectance_TrueColor",
        title="VIIRS SNPP True Colour (M5/M4/M3)",
        modality="optical", platform="Suomi-NPP", instrument="VIIRS",
        resolution_m=375, bands=("red", "green", "blue"), start="2015-11-24",
        description="375 m true colour - sharper than MODIS for urban scenes.",
    ),
    "viirs_snpp_m11i2i1": GibsLayer(
        id="VIIRS_SNPP_CorrectedReflectance_BandsM11-I2-I1",
        title="VIIRS SNPP SWIR/NIR/Red (M11/I2/I1)",
        modality="multispectral", platform="Suomi-NPP", instrument="VIIRS",
        resolution_m=375, bands=("swir2", "nir", "red"), start="2015-11-24",
        description="375 m SWIR-NIR-Red composite for water and burn mapping.",
    ),
    "opera_rtc_s1": GibsLayer(
        id="OPERA_L2_Radiometric_Terrain_Corrected_SAR_Sentinel-1",
        title="OPERA RTC Sentinel-1 SAR (gamma-0)",
        modality="sar", platform="Sentinel-1", instrument="C-SAR",
        resolution_m=30, bands=("vv", "vh", "vv"), cadence_days=6,
        start="2023-12-15",
        description=(
            "Radiometrically terrain-corrected C-band SAR backscatter. Cloud- and "
            "illumination-independent; low backscatter marks smooth water, high "
            "backscatter marks built-up double-bounce."
        ),
    ),
    "opera_dswx_s1": GibsLayer(
        id="OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1",
        title="OPERA Dynamic Surface Water Extent (S1)",
        modality="derived", platform="Sentinel-1", instrument="C-SAR",
        resolution_m=30, bands=("class", "class", "class"), cadence_days=6,
        start="2023-12-15", colorised=True,
        description="Operational open-water / inundation classification from SAR.",
    ),
    "modis_terra_ndvi_16day": GibsLayer(
        id="MODIS_Terra_L3_NDVI_16Day",
        title="MODIS Terra NDVI 16-Day (L3)",
        modality="derived", platform="Terra", instrument="MODIS",
        resolution_m=250, bands=("ndvi", "ndvi", "ndvi"), cadence_days=16,
        start="2000-03-05", colorised=True,
        description="Official MOD13 NDVI composite, palette-rendered.",
    ),
    "modis_terra_lst_day": GibsLayer(
        id="MODIS_Terra_L3_Land_Surface_Temp_8Day_Day",
        title="MODIS Terra Land Surface Temperature (8-day, day)",
        modality="thermal", platform="Terra", instrument="MODIS",
        resolution_m=1000, bands=("lst", "lst", "lst"), cadence_days=8,
        start="2000-03-05", colorised=True,
        description="Daytime land surface temperature, palette-rendered.",
    ),
}

#: Composite pairs that stack into a multispectral cube, best sensor first.
CUBE_SETS: tuple[tuple[str, str], ...] = (
    ("modis_terra_truecolor", "modis_terra_721"),
    ("modis_aqua_truecolor", "modis_aqua_721"),
    ("viirs_snpp_truecolor", "viirs_snpp_m11i2i1"),
)


class GibsError(RuntimeError):
    pass


class NoCoverageError(GibsError):
    """The archive answered, but there are no pixels for this AOI/date."""


# --------------------------------------------------------------------------
# Raster container
# --------------------------------------------------------------------------
@dataclass
class Raster:
    """A fetched image plus everything needed to defend where it came from."""

    array: np.ndarray            # (H, W, 3) uint8 RGB
    alpha: np.ndarray            # (H, W) uint8 coverage mask
    bbox: list[float]            # [w, s, e, n] EPSG:4326
    layer: GibsLayer
    date: str
    provenance: Provenance

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape[0], self.array.shape[1]

    @property
    def valid_mask(self) -> np.ndarray:
        return self.alpha > 10

    @property
    def coverage(self) -> float:
        return float(self.valid_mask.mean())

    def band(self, name: str) -> np.ndarray | None:
        """Return a 0..1 float band by semantic name, or None if absent."""
        try:
            idx = self.layer.bands.index(name)
        except ValueError:
            return None
        return self.array[..., idx].astype(np.float32) / 255.0


# --------------------------------------------------------------------------
# HTTP + cache
# --------------------------------------------------------------------------
_session = requests.Session()
_session.headers.update({"User-Agent": "SatQueryAI/1.0 (SIH26167 Avengers)"})


def _cache_key(**kw) -> str:
    blob = json.dumps(kw, sort_keys=True, default=str).encode()
    return hashlib.sha1(blob).hexdigest()[:20]


def _cache_path(key: str) -> "object":
    return settings.cache_dir / f"gibs_{key}.png"


def _fetch_png(layer_id: str, bbox: list[float], iso_date: str, size: int) -> bytes:
    """Raw WMS GetMap. WMS 1.3.0 + EPSG:4326 wants BBOX as south,west,north,east."""
    w, s, e, n = bbox
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "CRS": "EPSG:4326",
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
        "LAYERS": layer_id,
        "WIDTH": str(size),
        "HEIGHT": str(size),
        "BBOX": f"{s},{w},{n},{e}",
        "TIME": iso_date,
    }
    last: Exception | None = None
    for attempt in range(settings.http_retries + 1):
        try:
            r = _session.get(settings.gibs_wms_url, params=params, timeout=settings.http_timeout)
            if r.status_code != 200:
                raise GibsError(f"GIBS returned HTTP {r.status_code} for {layer_id}@{iso_date}")
            ctype = r.headers.get("Content-Type", "")
            if "xml" in ctype:
                raise GibsError(f"GIBS service exception for {layer_id}@{iso_date}: {r.text[:200]}")
            return r.content
        except Exception as exc:  # network hiccup -> short backoff, retry
            last = exc
            if attempt < settings.http_retries:
                time.sleep(0.6 * (attempt + 1))
    raise GibsError(f"GIBS fetch failed for {layer_id}@{iso_date}: {last}")


def request_url(layer_id: str, bbox: list[float], iso_date: str, size: int) -> str:
    """The exact URL we called - shown to the user as proof of provenance."""
    w, s, e, n = bbox
    return (
        f"{settings.gibs_wms_url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
        f"&CRS=EPSG:4326&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS={layer_id}"
        f"&WIDTH={size}&HEIGHT={size}&BBOX={s},{w},{n},{e}&TIME={iso_date}"
    )


def fetch_raster(
    layer_key: str,
    bbox: list[float],
    iso_date: str,
    size: int | None = None,
    min_coverage: float = 0.02,
) -> Raster:
    """Fetch one layer/date/AOI as a :class:`Raster`.

    Raises :class:`NoCoverageError` when the archive has no valid pixels -
    that is a legitimate answer and the agent surfaces it as "no data"
    rather than inventing anything.
    """
    layer = LAYERS[layer_key]
    size = size or settings.default_raster_size
    key = _cache_key(layer=layer.id, bbox=[round(v, 5) for v in bbox], d=iso_date, s=size)
    path = _cache_path(key)
    origin = DataOrigin.LIVE_SATELLITE
    raw: bytes | None = None

    if settings.cache_enabled and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < settings.cache_ttl_seconds:
            raw = path.read_bytes()
            origin = DataOrigin.CACHED_SATELLITE

    if raw is None:
        if settings.offline_mode:
            raise NoCoverageError(
                f"Offline mode is on and {layer.title} for {iso_date} is not in the local cache."
            )
        raw = _fetch_png(layer.id, bbox, iso_date, size)
        if settings.cache_enabled:
            try:
                path.write_bytes(raw)
            except OSError:
                pass

    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    arr = np.array(img)
    rgb, alpha = arr[..., :3], arr[..., 3]

    # GIBS returns a fully transparent tile when the sensor did not see this
    # spot on this date. Some layers return opaque black instead.
    coverage = float((alpha > 10).mean())
    if coverage < min_coverage:
        raise NoCoverageError(
            f"{layer.title} has no valid observation over this area on {iso_date} "
            f"(valid pixels: {coverage * 100:.1f}%)."
        )
    # GIBS can answer with an opaque but *empty* tile: the granule slot exists
    # for the date, yet no imagery was published into it. Those come back
    # almost pure black. They must be rejected here, because downstream every
    # band is then near-zero and the indices degenerate to ~0 - which would
    # look like a real, confident measurement instead of missing data.
    valid = alpha > 10
    if valid.any():
        brightness = rgb.astype(np.float32).mean(axis=2)[valid] / 255.0
        mean_brightness = float(brightness.mean())
        dark_frac = float((brightness < 0.02).mean())
        if mean_brightness < 0.035 or dark_frac > 0.97:
            raise NoCoverageError(
                f"{layer.title} returned an effectively empty scene for {iso_date} "
                f"(mean brightness {mean_brightness:.3f}, {dark_frac * 100:.0f}% of pixels "
                "black). The date slot exists in the archive but no imagery was published "
                "into it."
            )

    prov = Provenance(
        origin=origin,
        source=f"NASA GIBS / {layer.title}",
        source_url=request_url(layer.id, bbox, iso_date, size),
        instrument=layer.instrument,
        platform=layer.platform,
        modality=layer.modality,  # type: ignore[arg-type]
        acquisition_date=iso_date,
        resolution_m=layer.resolution_m,
        bbox=list(bbox),
        crs="EPSG:4326",
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        license="NASA EOSDIS - open, no restrictions on use",
        notes=(
            "Corrected-reflectance composites are byte-scaled for visualisation; "
            "derived indices are indicative, not calibrated surface reflectance."
            if layer.modality in {"optical", "multispectral"}
            else layer.description
        ),
    )
    return Raster(array=rgb, alpha=alpha, bbox=list(bbox), layer=layer, date=iso_date, provenance=prov)


# --------------------------------------------------------------------------
# Availability search - this is the PS's "input compatibility check"
# --------------------------------------------------------------------------
def _date_candidates(anchor: str, span: int, step: int = 1) -> list[str]:
    """Dates around *anchor*, nearest first."""
    d0 = date.fromisoformat(anchor)
    out: list[str] = [anchor]
    for k in range(step, span + 1, step):
        for delta in (-k, k):
            d = d0 + timedelta(days=delta)
            if d <= date.today():
                out.append(d.isoformat())
    return out


def probe_coverage(layer_key: str, bbox: list[float], iso_date: str, size: int = 128) -> float:
    """Cheap low-res probe: what fraction of the AOI did this sensor see?"""
    try:
        r = fetch_raster(layer_key, bbox, iso_date, size=size, min_coverage=0.0)
        return r.coverage
    except Exception:
        return 0.0


def cloud_fraction_rgb(rgb: np.ndarray, valid: np.ndarray) -> float:
    """Brightness/whiteness cloud proxy for a true-colour composite.

    Cloud tops are bright *and* spectrally flat: high mean reflectance with
    low saturation. Bright desert sand is also bright but noticeably warmer,
    so the saturation term matters.
    """
    if not valid.any():
        return 1.0
    a = rgb.astype(np.float32) / 255.0
    brightness = a.mean(axis=2)
    mx, mn = a.max(axis=2), a.min(axis=2)
    saturation = (mx - mn) / np.maximum(mx, 1e-6)
    cloudy = (brightness > 0.62) & (saturation < 0.28)
    return float(cloudy[valid].mean())


def probe_scene_quality(layer_key: str, bbox: list[float], iso_date: str,
                        size: int = 128) -> dict:
    """Coverage, darkness *and* clarity in one cheap probe.

    Three distinct failure modes have to be told apart, and conflating any two
    of them produces a confident answer about nothing:

    * **not covered** - the sensor never looked here (transparent tile);
    * **empty** - the archive slot exists but holds no imagery (black tile);
    * **clouded** - real imagery, but the surface is hidden.

    Ranking on clear fraction alone is actively dangerous, because a black
    tile contains no cloud and therefore scores *perfectly*. ``usable_fraction``
    below penalises all three, so the date search prefers a genuinely
    observed, genuinely visible surface.
    """
    try:
        r = fetch_raster(layer_key, bbox, iso_date, size=size, min_coverage=0.0)
        cov = r.coverage
        if cov <= 0:
            raise NoCoverageError("no valid pixels")
        cloud = cloud_fraction_rgb(r.array, r.valid_mask)
        brightness = r.array.astype(np.float32).mean(axis=2)[r.valid_mask] / 255.0
        dark = float((brightness < 0.02).mean())
        return {
            "date": iso_date,
            "coverage": round(cov, 4),
            "cloud_fraction": round(cloud, 4),
            "dark_fraction": round(dark, 4),
            "mean_brightness": round(float(brightness.mean()), 4),
            "clear_fraction": round(cov * (1.0 - cloud), 4),
            "usable_fraction": round(cov * (1.0 - cloud) * (1.0 - dark), 4),
        }
    except Exception:
        return {"date": iso_date, "coverage": 0.0, "cloud_fraction": 1.0,
                "dark_fraction": 1.0, "mean_brightness": 0.0,
                "clear_fraction": 0.0, "usable_fraction": 0.0}


def find_available_date(
    layer_key: str,
    bbox: list[float],
    anchor: str,
    span: int = 12,
    min_coverage: float = 0.5,
    step: int = 1,
    min_clear: float = 0.30,
) -> tuple[str | None, float, list[dict]]:
    """Search outward from *anchor* for a date the sensor usably observed.

    "Usable" means covered *and* reasonably cloud-free. Returns
    ``(best_date, clear_fraction, probe_log)``; the probe log goes straight
    into the execution trace so a judge can see the agent really checked.
    """
    cands = _date_candidates(anchor, span, step)
    log: list[dict] = []

    with cf.ThreadPoolExecutor(max_workers=settings.max_parallel_fetch) as ex:
        futures = {ex.submit(probe_scene_quality, layer_key, bbox, d): d for d in cands}
        for fut in cf.as_completed(futures):
            try:
                log.append(fut.result())
            except Exception:
                log.append({"date": futures[fut], "coverage": 0.0,
                            "cloud_fraction": 1.0, "clear_fraction": 0.0})

    log.sort(key=lambda r: r["date"])
    d0 = date.fromisoformat(anchor)

    def rank(rows: list[dict]) -> dict:
        # Best usable fraction, then closest to what the user actually asked for.
        return sorted(rows, key=lambda r: (-r["usable_fraction"],
                                           abs((date.fromisoformat(r["date"]) - d0).days)))[0]

    # A date is only a candidate if the sensor covered it AND the tile actually
    # holds imagery. Empty tiles are excluded outright - they are missing data,
    # not clear weather.
    observed = [r for r in log
                if r["coverage"] >= min_coverage and r.get("dark_fraction", 1.0) < 0.5]

    good = [r for r in observed if r["usable_fraction"] >= min_clear]
    if good:
        best = rank(good)
        return best["date"], best["usable_fraction"], log

    # Real imagery exists but it is cloudy: return the least-clouded date and
    # let the caller warn, rather than failing outright.
    if observed:
        best = rank(observed)
        return best["date"], best["usable_fraction"], log
    return None, 0.0, log


def fetch_cube(
    bbox: list[float],
    iso_date: str,
    size: int | None = None,
    prefer: str | None = None,
) -> tuple[dict[str, np.ndarray], list[Raster], np.ndarray]:
    """Fetch a co-registered multispectral cube for one date.

    Returns ``(bands, rasters, valid_mask)`` where *bands* maps semantic band
    names (blue, green, red, nir, swir2) to float arrays in 0..1.
    """
    size = size or settings.default_raster_size
    sets = list(CUBE_SETS)
    if prefer:
        sets.sort(key=lambda s: 0 if prefer in s[0] else 1)

    last_err: Exception | None = None
    for tc_key, ms_key in sets:
        try:
            with cf.ThreadPoolExecutor(max_workers=2) as ex:
                f_tc = ex.submit(fetch_raster, tc_key, bbox, iso_date, size)
                f_ms = ex.submit(fetch_raster, ms_key, bbox, iso_date, size)
                tc, ms = f_tc.result(), f_ms.result()
        except Exception as exc:
            last_err = exc
            continue

        bands: dict[str, np.ndarray] = {}
        for r in (tc, ms):
            for i, name in enumerate(r.layer.bands):
                # First writer wins, so TrueColor owns "red" (band 1 at 250 m).
                bands.setdefault(name, r.array[..., i].astype(np.float32) / 255.0)
        valid = tc.valid_mask & ms.valid_mask
        return bands, [tc, ms], valid

    raise NoCoverageError(
        f"No optical sensor (MODIS Terra/Aqua, VIIRS) had a usable observation "
        f"of this area on {iso_date}. Last error: {last_err}"
    )


def sar_repeat_dates(anchor: str, count: int = 6, cycle: int = 12) -> list[str]:
    """Sentinel-1 revisits a given track on a fixed cycle; generate candidates."""
    d0 = date.fromisoformat(anchor)
    out = []
    for k in range(-count, count + 1):
        d = d0 + timedelta(days=k * cycle)
        if d <= date.today():
            out.append(d.isoformat())
    return out


def layer_catalog() -> list[dict]:
    """Serialisable catalogue for the /api/catalog endpoint."""
    return [
        {
            "key": k,
            "id": v.id,
            "title": v.title,
            "modality": v.modality,
            "platform": v.platform,
            "instrument": v.instrument,
            "resolution_m": v.resolution_m,
            "bands": list(v.bands),
            "cadence_days": v.cadence_days,
            "start": v.start,
            "description": v.description,
            "colorised": v.colorised,
        }
        for k, v in LAYERS.items()
    ]
