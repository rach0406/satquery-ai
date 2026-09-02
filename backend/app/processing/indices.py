"""Spectral indices and threshold-based land-cover segmentation.

Everything here is a deterministic function of real pixel values. No model
guesses a number; each index is the textbook normalised-difference formula
applied to the bands we actually retrieved.

Index definitions and the literature they come from:

======  ==========================  =================================
index   formula                     reference
======  ==========================  =================================
NDVI    (NIR - Red)/(NIR + Red)     Rouse et al. 1974
NDWI    (Green - NIR)/(Green+NIR)   McFeeters 1996
MNDWI   (Green - SWIR)/(Green+SWIR) Xu 2006
NBR     (NIR - SWIR2)/(NIR+SWIR2)   Key & Benson 2006
NDBI    (SWIR - NIR)/(SWIR + NIR)   Zha et al. 2003
BSI     ((SWIR+Red)-(NIR+Blue))/    Rikimaru et al. 2002
        ((SWIR+Red)+(NIR+Blue))
VARI    (Green-Red)/(Green+Red-Blue) Gitelson et al. 2002
======  ==========================  =================================
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-6

#: Minimum Otsu separability before a class split is believed.
#:
#: The value is not arbitrary. Otsu applied to a *single* normal distribution
#: cuts at the mean, which yields
#:
#:     eta = sigma^2_between / sigma^2_total = 2 / pi ~= 0.637
#:
#: So any gate at or below 0.637 can never reject a unimodal population - it
#: would happily split a uniform salt flat in half and call one half built-up.
#: The gates below sit above that analytic floor with margin.
UNIMODAL_GAUSSIAN_ETA = 2.0 / np.pi   # ~0.6366
BIMODALITY_MIN = 0.75

#: Built-up needs a stricter gate still: NDBI cannot tell urban fabric from salt
#: crust or dry sand at coarse resolution, so the split is only believed when
#: the histogram is clearly bimodal *and* the two sub-populations are far apart.
BUILTUP_SEPARABILITY_MIN = 0.82
BUILTUP_GAP_MIN = 0.18

#: Open water reflects more green than SWIR. Below this, a pixel is not water,
#: whatever the adaptive threshold search would like to claim.
WATER_INDEX_FLOOR = 0.02

#: Bands each index needs. The agent checks this before promising an answer.
INDEX_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "NDVI": ("nir", "red"),
    "NDWI": ("green", "nir"),
    "MNDWI": ("green", "swir2"),
    "NBR": ("nir", "swir2"),
    "NDBI": ("swir2", "nir"),
    "BSI": ("swir2", "red", "nir", "blue"),
    "VARI": ("green", "red", "blue"),
}

INDEX_META: dict[str, dict[str, str]] = {
    "NDVI": {"name": "Normalised Difference Vegetation Index",
             "reads": "vegetation vigour", "range": "-1 to +1",
             "reference": "Rouse et al., 1974"},
    "NDWI": {"name": "Normalised Difference Water Index",
             "reads": "open water (McFeeters)", "range": "-1 to +1",
             "reference": "McFeeters, 1996"},
    "MNDWI": {"name": "Modified NDWI",
              "reads": "open water, suppresses built-up noise", "range": "-1 to +1",
              "reference": "Xu, 2006"},
    "NBR": {"name": "Normalised Burn Ratio",
            "reads": "burn severity / vegetation moisture", "range": "-1 to +1",
            "reference": "Key & Benson, 2006"},
    "NDBI": {"name": "Normalised Difference Built-up Index",
             "reads": "impervious / built-up surface", "range": "-1 to +1",
             "reference": "Zha et al., 2003"},
    "BSI": {"name": "Bare Soil Index", "reads": "exposed soil",
            "range": "-1 to +1", "reference": "Rikimaru et al., 2002"},
    "VARI": {"name": "Visible Atmospherically Resistant Index",
             "reads": "greenness from RGB only", "range": "-1 to +1",
             "reference": "Gitelson et al., 2002"},
}

#: Land-cover classes produced by :func:`segment_landcover`.
LANDCOVER_CLASSES: tuple[str, ...] = (
    "water", "dense_vegetation", "sparse_vegetation", "built_up", "bare_soil", "cloud_or_snow",
)

#: Thematic land-cover palette.
#:
#: Validated on the dark chart surface (#131c2e) with the all-pairs check:
#: normal-vision worst pair dE 22.0 (floor 15, PASS), CVD worst pair dE 6.8
#: (the 6-8 band, which is legal only with secondary encoding - every class map
#: and every legend here ships the class name and its measured value beside the
#: swatch, which is that encoding).
#:
#: Lightness is deliberately spread across the classes rather than held in a
#: uniform band. That is a documented deviation from the categorical default:
#: uniform lightness collapsed the worst normal-vision pair to dE 10.6, and
#: varying lightness is the standard cartographic technique for a thematic
#: class map. Lightness also survives all three CVD simulations, so it is the
#: channel doing the real work.
CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "water": (37, 99, 235),             # #2563eb  dark blue
    "dense_vegetation": (21, 128, 61),  # #15803d  dark green
    "sparse_vegetation": (163, 230, 53),  # #a3e635  light yellow-green
    "built_up": (244, 114, 182),        # #f472b6  light magenta (RS convention)
    "bare_soil": (180, 83, 9),          # #b45309  dark ochre
    "cloud_or_snow": (241, 245, 249),   # #f1f5f9  near-white (obscured, not a surface class)
    "unclassified": (100, 116, 139),    # #64748b  neutral
}

CLASS_LABELS: dict[str, str] = {
    "water": "Water",
    "dense_vegetation": "Dense vegetation",
    "sparse_vegetation": "Sparse vegetation / cropland",
    "built_up": "Built-up / impervious",
    "bare_soil": "Bare soil",
    "cloud_or_snow": "Cloud or snow",
    "unclassified": "Unclassified",
}


def normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b) / np.maximum(a + b, EPS)


def compute_index(name: str, bands: dict[str, np.ndarray]) -> np.ndarray:
    """Compute one index. Raises KeyError if a required band is missing."""
    name = name.upper()
    need = INDEX_REQUIREMENTS.get(name)
    if need is None:
        raise KeyError(f"Unknown index {name!r}")
    missing = [b for b in need if b not in bands]
    if missing:
        raise KeyError(f"{name} needs band(s) {missing} which this sensor stack does not provide")

    if name == "NDVI":
        return normalised_difference(bands["nir"], bands["red"])
    if name == "NDWI":
        return normalised_difference(bands["green"], bands["nir"])
    if name == "MNDWI":
        return normalised_difference(bands["green"], bands["swir2"])
    if name == "NBR":
        return normalised_difference(bands["nir"], bands["swir2"])
    if name == "NDBI":
        return normalised_difference(bands["swir2"], bands["nir"])
    if name == "BSI":
        num = (bands["swir2"] + bands["red"]) - (bands["nir"] + bands["blue"])
        den = (bands["swir2"] + bands["red"]) + (bands["nir"] + bands["blue"])
        return num / np.maximum(den, EPS)
    if name == "VARI":
        den = bands["green"] + bands["red"] - bands["blue"]
        return (bands["green"] - bands["red"]) / np.where(np.abs(den) < EPS, EPS, den)
    raise KeyError(name)


def available_indices(bands: dict[str, np.ndarray]) -> list[str]:
    return [k for k, need in INDEX_REQUIREMENTS.items() if all(b in bands for b in need)]


@dataclass
class IndexStats:
    name: str
    mean: float
    median: float
    std: float
    minimum: float
    maximum: float
    p10: float
    p90: float
    valid_pixels: int
    histogram: list[int]
    bin_edges: list[float]

    def as_dict(self) -> dict:
        return {
            "name": self.name, "mean": self.mean, "median": self.median, "std": self.std,
            "min": self.minimum, "max": self.maximum, "p10": self.p10, "p90": self.p90,
            "valid_pixels": self.valid_pixels,
            "histogram": self.histogram, "bin_edges": self.bin_edges,
        }


def index_stats(arr: np.ndarray, mask: np.ndarray, name: str, bins: int = 40) -> IndexStats:
    """Descriptive statistics over the valid pixels only."""
    vals = arr[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return IndexStats(name, *(float("nan"),) * 7, 0, [], [])
    hist, edges = np.histogram(vals, bins=bins, range=(-1.0, 1.0))
    return IndexStats(
        name=name,
        mean=float(np.mean(vals)),
        median=float(np.median(vals)),
        std=float(np.std(vals)),
        minimum=float(np.min(vals)),
        maximum=float(np.max(vals)),
        p10=float(np.percentile(vals, 10)),
        p90=float(np.percentile(vals, 90)),
        valid_pixels=int(vals.size),
        histogram=[int(v) for v in hist],
        bin_edges=[float(v) for v in edges],
    )


def otsu_with_separability(values: np.ndarray, bins: int = 256) -> tuple[float, float]:
    """Otsu's threshold *and* its separability.

    Otsu always returns a cut, even for a perfectly unimodal population - it
    will happily bisect a uniform salt flat and report half of it as
    "built-up". The separability measure

        eta = sigma^2_between / sigma^2_total   in [0, 1]

    says whether that cut corresponds to a real gap in the histogram. Callers
    use it as a gate: no bimodality, no split, and the scene is reported as one
    class rather than two invented ones.
    """
    values = values[np.isfinite(values)]
    if values.size < 16:
        return (float(np.median(values)) if values.size else 0.0), 0.0
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi - lo < 1e-9:
        return lo, 0.0
    hist, edges = np.histogram(values, bins=bins, range=(lo, hi))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return lo, 0.0
    centres = (edges[:-1] + edges[1:]) / 2.0
    w0 = np.cumsum(hist) / total
    w1 = 1.0 - w0
    m0 = np.cumsum(hist * centres) / np.maximum(np.cumsum(hist), 1e-9)
    total_mean = float((hist * centres).sum() / total)
    m1 = (total_mean - w0 * m0) / np.maximum(w1, 1e-9)
    between = w0 * w1 * (m0 - m1) ** 2
    between[~np.isfinite(between)] = -1
    k = int(np.argmax(between))
    var_total = float(np.var(values))
    eta = float(between[k] / var_total) if var_total > 1e-12 else 0.0
    return float(centres[k]), float(np.clip(eta, 0.0, 1.0))


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    """Otsu's method - used to split change/no-change and water/land."""
    return otsu_with_separability(values, bins)[0]


@dataclass
class Segmentation:
    labels: np.ndarray               # (H, W) int, index into LANDCOVER_CLASSES, -1 = invalid
    fractions: dict[str, float]      # class -> fraction of valid pixels
    pixel_counts: dict[str, int]
    thresholds: dict[str, float]
    valid_pixels: int
    method: str
    notes: list[str]
    #: Which band set the segmentation actually ran on. "multispectral" uses the
    #: NIR/SWIR physics; "rgb" uses the visible-only proxies in
    #: :func:`segment_landcover_rgb`, which are weaker and say so.
    basis: str = "multispectral"


#: Bands the full multispectral segmentation needs. Anything less falls back to
#: :func:`segment_landcover_rgb`.
MULTISPECTRAL_SEGMENTATION_BANDS: tuple[str, ...] = ("nir", "red")

#: Visible-only water detection: liquid water absorbs red far more strongly than
#: blue, so a positive blue-minus-red normalised difference *plus* genuine
#: darkness is the most transferable RGB water signature. Neither alone is
#: sufficient - blue paint is blue but not dark, and shadow is dark but not blue.
RGB_WATER_MIN_BLUENESS = 0.02


def has_multispectral_bands(bands: dict[str, np.ndarray]) -> bool:
    """True when the physics-based segmentation can run on this band stack."""
    return all(b in bands for b in MULTISPECTRAL_SEGMENTATION_BANDS)


def segment_landcover_rgb(
    bands: dict[str, np.ndarray],
    mask: np.ndarray,
    adaptive: bool = True,
) -> Segmentation:
    """Land-cover segmentation for a visible-only (RGB) image.

    An ordinary photograph, a screenshot or an RGB benchmark chip has no
    near-infrared band, so NDVI, NDWI, MNDWI, NBR and NDBI are all undefined -
    every one of them needs NIR or SWIR. Refusing to analyse such an image at
    all is the wrong answer, but so is silently substituting an NIR-based
    threshold with a visible-light one and presenting the result as equivalent.

    So this path uses the established RGB-only proxies and labels itself
    honestly as the weaker basis:

    * **vegetation** - VARI, (G - R) / (G + R - B), Gitelson et al. 2002. This
      is the standard visible-band greenness index and is what the EuroSAT
      feature extractor in :mod:`app.ml.features` already relies on.
    * **water** - normalised blue-minus-red combined with a darkness test.
    * **built-up / bare** - bright, low-saturation surfaces separated from dark
      ones by an Otsu cut on brightness.

    The same bimodality discipline as the multispectral path applies: a split
    is only believed when the histogram actually contains one, so a uniform
    image is not carved into classes that are not there.
    """
    h, w = mask.shape
    labels = np.full((h, w), -1, dtype=np.int16)
    thresholds: dict[str, float] = {}
    notes: list[str] = [
        "This image has no near-infrared band, so NDVI/NDWI/MNDWI/NBR/NDBI cannot be "
        "computed. Land cover was derived from visible-band proxies (VARI greenness, "
        "blue-red water contrast, brightness) instead. These are genuinely weaker than "
        "the NIR-based physics and the classes should be read as indicative."
    ]
    idx = {name: LANDCOVER_CLASSES.index(name) for name in LANDCOVER_CLASSES}

    r, g, b = bands["red"], bands["green"], bands["blue"]
    brightness = (r + g + b) / 3.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    saturation = (mx - mn) / np.maximum(mx, EPS)

    is_valid = mask

    # --- cloud / snow / blown-out highlights ------------------------------
    thresholds["cloud_snow_brightness"] = 0.85
    cloud = is_valid & (brightness > 0.85) & (saturation < 0.15)
    labels[cloud] = idx["cloud_or_snow"]

    rest = is_valid & ~cloud
    if not rest.any():
        return _finalise_segmentation(
            labels, is_valid, thresholds, notes,
            "RGB visible-only: scene is entirely cloud/highlight", basis="rgb")

    # --- water: blue-dominant AND dark ------------------------------------
    blueness = normalised_difference(b, r)
    water = np.zeros_like(rest)
    if adaptive:
        t_blue, eta_blue = otsu_with_separability(blueness[rest])
        t_blue = float(np.clip(t_blue, RGB_WATER_MIN_BLUENESS, 0.45))
        thresholds["water_blueness"] = round(t_blue, 4)
        thresholds["water_blueness_separability"] = round(eta_blue, 4)
        dark_cut = float(np.percentile(brightness[rest], 45))
        thresholds["water_darkness_cut"] = round(dark_cut, 4)
        if eta_blue < BIMODALITY_MIN:
            notes.append(
                f"Blue-red contrast is unimodal over this image (separability "
                f"{eta_blue:.2f} < {BIMODALITY_MIN}), so no water/land split was believed "
                "and the literature-style floor was used instead. A dry or indoor scene is "
                "therefore not carved into 'water'.")
            t_blue = 0.12
        water = rest & (blueness > t_blue) & (brightness < dark_cut)
    labels[water] = idx["water"]

    # --- vegetation via VARI ----------------------------------------------
    land = rest & ~water
    vari = compute_index("VARI", bands)
    if land.sum() > 256 and adaptive:
        t_veg = float(np.clip(otsu_threshold(vari[land]), 0.02, 0.45))
        veg = land & (vari >= t_veg)
        if veg.sum() > 128:
            t_dense = float(np.clip(otsu_threshold(vari[veg]), t_veg + 0.02, 0.8))
        else:
            t_dense = t_veg + 0.10
    else:
        t_veg, t_dense = 0.05, 0.20
    thresholds["vegetation_VARI"] = round(t_veg, 4)
    thresholds["dense_vegetation_VARI"] = round(t_dense, 4)

    dense = land & (vari >= t_dense)
    sparse = land & (vari >= t_veg) & (vari < t_dense)
    low = land & (vari < t_veg)
    labels[dense] = idx["dense_vegetation"]
    labels[sparse] = idx["sparse_vegetation"]

    # --- built-up vs bare soil on brightness ------------------------------
    # Same caution as the NDBI path: only split when the histogram really is
    # bimodal, otherwise everything non-vegetated stays "bare soil".
    if low.sum() > 256 and adaptive:
        t_built, eta = otsu_with_separability(brightness[low])
        hi_grp = low & (brightness >= t_built)
        lo_grp = low & (brightness < t_built)
        gap = (float(brightness[hi_grp].mean() - brightness[lo_grp].mean())
               if hi_grp.any() and lo_grp.any() else 0.0)
        thresholds["built_up_brightness"] = round(float(t_built), 4)
        thresholds["built_up_separability"] = round(eta, 4)
        thresholds["built_up_class_gap"] = round(gap, 4)
        if eta >= BIMODALITY_MIN and gap >= 0.08:
            labels[hi_grp] = idx["built_up"]
            labels[lo_grp] = idx["bare_soil"]
        else:
            notes.append(
                f"Brightness over the non-vegetated pixels is not clearly bimodal "
                f"(separability {eta:.2f}, class gap {gap:.2f}), so those pixels are "
                "reported as bare soil rather than split into built-up. Without NIR or "
                "radar there is no reliable way to separate pavement from dry ground.")
            labels[low] = idx["bare_soil"]
    else:
        labels[low] = idx["bare_soil"]

    method = (
        f"RGB visible-only: VARI vegetation cuts at {t_veg:+.3f} (vegetated) and "
        f"{t_dense:+.3f} (dense); blue-red water cut at "
        f"{thresholds.get('water_blueness', 0.12):+.3f} with a darkness test; "
        "brightness-Otsu built-up split"
    )
    return _finalise_segmentation(labels, is_valid, thresholds, notes, method, basis="rgb")


def _finalise_segmentation(labels, is_valid, thresholds, notes, method,
                           basis: str = "multispectral") -> Segmentation:
    """Count classes and pack the result. Shared by both segmentation paths."""
    idx = {name: LANDCOVER_CLASSES.index(name) for name in LANDCOVER_CLASSES}
    valid_n = int(is_valid.sum())
    counts: dict[str, int] = {}
    fractions: dict[str, float] = {}
    for name in LANDCOVER_CLASSES:
        c = int((labels == idx[name]).sum())
        counts[name] = c
        fractions[name] = (c / valid_n) if valid_n else 0.0
    return Segmentation(
        labels=labels, fractions=fractions, pixel_counts=counts,
        thresholds=thresholds, valid_pixels=valid_n, notes=notes,
        method=method, basis=basis,
    )


def segment_landcover(
    bands: dict[str, np.ndarray],
    mask: np.ndarray,
    adaptive: bool = True,
) -> Segmentation:
    """Threshold-based land-cover segmentation on real spectral indices.

    Dispatches on what the band stack can actually support: the NIR/SWIR physics
    below when the bands are there, and :func:`segment_landcover_rgb` when the
    image is visible-only. Both paths return the same :class:`Segmentation`
    shape, with ``basis`` recording which one ran.

    Why the vegetation cuts are adaptive rather than the textbook constants
    ---------------------------------------------------------------------
    The literature values (NDVI 0.35 for closed canopy, 0.15 for sparse) are
    defined on *calibrated surface reflectance*. The imagery we retrieve from
    GIBS is a byte-scaled visualisation product with a non-linear stretch, so
    its NDVI is compressed towards zero: a mangrove canopy that reads 0.6 in
    Level-2 reflectance can read ~0.26 here. Applying the textbook constant to
    that distribution silently reclassifies healthy forest as bare soil.

    So when ``adaptive`` is set, the vegetation split is placed by Otsu on the
    NDVI distribution of the *land* pixels themselves, bounded to a sane range,
    and the resulting cut is reported in :attr:`Segmentation.thresholds` and in
    the method string. The classes then mean "vegetated relative to this
    scene", which is what the data can actually support.
    """
    if not has_multispectral_bands(bands):
        if all(b in bands for b in ("red", "green", "blue")):
            return segment_landcover_rgb(bands, mask, adaptive=adaptive)
        raise ValueError(
            "Land-cover segmentation needs either NIR+Red (multispectral path) or "
            f"Red+Green+Blue (visible-only path). This scene provides {sorted(bands)}."
        )

    h, w = mask.shape
    labels = np.full((h, w), -1, dtype=np.int16)
    thresholds: dict[str, float] = {}
    notes: list[str] = []

    idx = {name: LANDCOVER_CLASSES.index(name) for name in LANDCOVER_CLASSES}

    water_index_name = "MNDWI" if "swir2" in bands and "green" in bands else "NDWI"
    try:
        water_idx = compute_index(water_index_name, bands)
    except KeyError:
        water_index_name = "NDVI"
        water_idx = -compute_index("NDVI", bands)

    # Adaptive water cut, clamped to a sane band so a cloud-free desert scene
    # does not "discover" water where there is none.
    if adaptive:
        t_water, eta_w = otsu_with_separability(water_idx[mask])
        # Physical floor: open water reflects more green than SWIR, so MNDWI
        # over water is positive. Sand, salt crust and bare rock are always
        # negative. Clamping a strongly negative desert threshold *up* into
        # this range is what turns a dune field into 25% "water", so the
        # lower bound is the physics, not a tuning constant.
        t_water = float(np.clip(t_water, WATER_INDEX_FLOOR, 0.45))
        thresholds[f"water_{water_index_name}_separability"] = round(eta_w, 4)
        if eta_w < BIMODALITY_MIN:
            # No water/land gap in the histogram - an arid scene. Fall back to
            # the literature cut, which will simply find nothing, rather than
            # bisecting dry ground into "water".
            notes.append(
                f"{water_index_name} is unimodal over this scene (separability "
                f"{eta_w:.2f} < {BIMODALITY_MIN}); the literature water cut was used instead "
                "of an adaptive one, so a genuinely dry scene is not split into water.")
            t_water = 0.10
    else:
        t_water = 0.0
    thresholds[f"water_{water_index_name}"] = t_water

    ndvi = compute_index("NDVI", bands) if all(b in bands for b in ("nir", "red")) else None
    ndbi = compute_index("NDBI", bands) if all(b in bands for b in ("swir2", "nir")) else None

    brightness = np.mean([bands[b] for b in ("red", "green", "blue") if b in bands], axis=0)
    thresholds["cloud_snow_brightness"] = 0.82

    is_valid = mask
    cloud = is_valid & (brightness > 0.82)
    if ndvi is not None:
        cloud &= ndvi < 0.25
    water = is_valid & ~cloud & (water_idx > t_water)
    if ndvi is not None:
        water &= ndvi < 0.20

    # Physical confirmation in the near-infrared.
    #
    # A normalised index is a *ratio*, so atmospheric haze - which lifts green
    # reflectance across the whole scene - shifts the entire MNDWI distribution
    # upward and can push dry land above any absolute cut. Liquid water,
    # however, absorbs NIR almost completely under every illumination and
    # stretch, so the dark NIR mode is the single most transferable water
    # signature available. Requiring both the ratio and the NIR evidence stops
    # a hazy delta scene from being reported as 82% water.
    if "nir" in bands:
        nir = bands["nir"]
        nir_cut, nir_eta = otsu_with_separability(nir[is_valid & ~cloud])
        if nir_eta < BIMODALITY_MIN:
            # No dark/bright NIR split: use a conservative low percentile so
            # only genuinely dark pixels qualify.
            nir_cut = float(np.percentile(nir[is_valid & ~cloud], 35))
            notes.append(
                f"NIR is unimodal over this scene (separability {nir_eta:.2f}); the water "
                "mask was confirmed against the darkest 35% of NIR pixels rather than an "
                "Otsu split.")
        thresholds["water_NIR_cut"] = round(float(nir_cut), 4)
        thresholds["water_NIR_separability"] = round(float(nir_eta), 4)
        water &= nir < nir_cut

    rest = is_valid & ~cloud & ~water
    labels[cloud] = idx["cloud_or_snow"]
    labels[water] = idx["water"]

    if ndvi is not None:
        if adaptive and rest.sum() > 256:
            # Split vegetated from non-vegetated on this scene's own NDVI
            # distribution, then split the vegetated part again for canopy
            # density. Bounds keep a uniformly bare or uniformly forested
            # scene from inventing a split that is not there.
            t_veg = float(np.clip(otsu_threshold(ndvi[rest]), 0.04, 0.40))
            veg = rest & (ndvi >= t_veg)
            if veg.sum() > 128:
                t_dense = float(np.clip(otsu_threshold(ndvi[veg]), t_veg + 0.02, 0.75))
            else:
                t_dense = t_veg + 0.10
        else:
            t_veg, t_dense = 0.15, 0.35
        thresholds["vegetation_NDVI"] = t_veg
        thresholds["dense_vegetation_NDVI"] = t_dense

        dense = rest & (ndvi >= t_dense)
        sparse = rest & (ndvi >= t_veg) & (ndvi < t_dense)
        low = rest & (ndvi < t_veg)
        labels[dense] = idx["dense_vegetation"]
        labels[sparse] = idx["sparse_vegetation"]
        if ndbi is not None and low.sum() > 256:
            # Built-up vs bare soil is the least reliable split available from
            # optical indices: at 250 m, salt flats, dry sand and urban fabric
            # all read as high NDBI. So the split only happens when the NDBI
            # histogram is genuinely bimodal - otherwise the pixels stay
            # "bare soil" and a note records that no separable built-up
            # signature was found. SAR is the right instrument for this, and
            # the SAR analyser provides it when a radar scene is present.
            t_built, eta = otsu_with_separability(ndbi[low])
            t_built = float(np.clip(t_built, -0.05, 0.45))
            hi_grp = low & (ndbi >= t_built)
            lo_grp = low & (ndbi < t_built)
            gap = (float(ndbi[hi_grp].mean() - ndbi[lo_grp].mean())
                   if hi_grp.any() and lo_grp.any() else 0.0)
            thresholds["built_up_NDBI"] = t_built
            thresholds["built_up_separability"] = round(eta, 4)
            thresholds["built_up_class_gap"] = round(gap, 4)
            if eta >= BUILTUP_SEPARABILITY_MIN and gap >= BUILTUP_GAP_MIN:
                labels[hi_grp] = idx["built_up"]
                labels[lo_grp] = idx["bare_soil"]
            else:
                notes.append(
                    f"No separable built-up signature was found in NDBI over the "
                    f"non-vegetated pixels (separability {eta:.2f}, class gap {gap:.2f}; "
                    f"need {BUILTUP_SEPARABILITY_MIN} and {BUILTUP_GAP_MIN}), so those pixels "
                    "are reported as bare soil rather than split. At 250 m, salt crust, dry "
                    "sand and urban fabric all read as high NDBI and are not reliably "
                    "separable by optical index alone - SAR double-bounce is the appropriate "
                    "discriminator, and the SAR analyser supplies it when a radar scene is "
                    "available."
                )
                labels[low] = idx["bare_soil"]
        else:
            labels[low] = idx["bare_soil"]
    else:
        labels[rest] = idx["bare_soil"]

    method = (
        f"Otsu-adaptive {water_index_name} water cut at {t_water:+.3f}; "
        + (f"scene-adaptive NDVI cuts at {thresholds.get('vegetation_NDVI', 0.15):+.3f} "
           f"(vegetated) and {thresholds.get('dense_vegetation_NDVI', 0.35):+.3f} (dense); "
           f"adaptive NDBI built-up cut at {thresholds.get('built_up_NDBI', 0.02):+.3f}"
           if adaptive else
           "literature NDVI cuts 0.35/0.15; NDBI 0.02 built-up cut")
    )
    return _finalise_segmentation(labels, is_valid, thresholds, notes, method,
                                  basis="multispectral")


def colorise_labels(labels: np.ndarray) -> np.ndarray:
    """Render a label map to an RGBA overlay for the map view."""
    h, w = labels.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for i, name in enumerate(LANDCOVER_CLASSES):
        m = labels == i
        if not m.any():
            continue
        r, g, b = CLASS_COLORS[name]
        out[m] = (r, g, b, 200)
    return out


#: Perceptually ordered ramp for signed index maps (red -> grey -> green).
def colorise_index(arr: np.ndarray, mask: np.ndarray, vmin: float = -1.0,
                   vmax: float = 1.0, palette: str = "rdylgn") -> np.ndarray:
    """Map a float index array to an RGBA overlay."""
    h, w = arr.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    t = np.clip((arr - vmin) / max(vmax - vmin, EPS), 0.0, 1.0)

    if palette == "rdylgn":
        stops = [(0.0, (178, 24, 43)), (0.25, (239, 138, 98)), (0.5, (247, 247, 247)),
                 (0.75, (133, 200, 130)), (1.0, (26, 120, 55))]
    elif palette == "blues":
        stops = [(0.0, (247, 251, 255)), (0.5, (107, 174, 214)), (1.0, (8, 48, 107))]
    elif palette == "magma":
        stops = [(0.0, (0, 0, 4)), (0.25, (81, 18, 124)), (0.5, (183, 55, 121)),
                 (0.75, (252, 137, 97)), (1.0, (252, 253, 191))]
    elif palette == "coolwarm":
        stops = [(0.0, (59, 76, 192)), (0.5, (221, 221, 221)), (1.0, (180, 4, 38))]
    else:  # greys
        stops = [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))]

    xs = np.array([s[0] for s in stops])
    cs = np.array([s[1] for s in stops], dtype=np.float64)
    rgb = np.stack([np.interp(t, xs, cs[:, c]) for c in range(3)], axis=-1)
    out[..., :3] = rgb.astype(np.uint8)
    out[..., 3] = np.where(mask, 210, 0).astype(np.uint8)
    return out
