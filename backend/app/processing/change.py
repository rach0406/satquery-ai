"""Bi-temporal change analysis.

Two complementary detectors, both classical and both fully deterministic:

* **Change Vector Analysis (CVA)** - Malila (1980). Treat each pixel as a
  vector in band space, take the Euclidean norm of the difference between
  dates, then split change/no-change with an Otsu cut on the magnitude.
* **Index differencing** - per-index delta maps (dNDVI, dMNDWI, dNBR) plus a
  class-transition matrix built from the two segmentations.

The transition matrix is what makes "what changed and where" answerable with
actual numbers instead of an adjective.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .indices import (
    LANDCOVER_CLASSES,
    Segmentation,
    compute_index,
    otsu_threshold,
)


@dataclass
class ChangeResult:
    magnitude: np.ndarray                     # (H, W) CVA magnitude
    change_mask: np.ndarray                   # (H, W) bool
    threshold: float
    changed_fraction: float
    changed_pixels: int
    valid_pixels: int
    index_deltas: dict[str, np.ndarray] = field(default_factory=dict)
    index_delta_stats: dict[str, dict] = field(default_factory=dict)
    transitions: list[dict] = field(default_factory=list)
    class_deltas: dict[str, dict] = field(default_factory=dict)
    direction: np.ndarray | None = None       # signed dominant-index change
    method: str = ""


def change_vector_analysis(
    bands_a: dict[str, np.ndarray],
    bands_b: dict[str, np.ndarray],
    mask: np.ndarray,
) -> tuple[np.ndarray, float, np.ndarray]:
    """CVA magnitude, Otsu threshold, and the resulting change mask."""
    common = [b for b in sorted(bands_a) if b in bands_b]
    if not common:
        raise ValueError("The two dates share no common bands - cannot compare them.")
    diff = np.stack([bands_b[b] - bands_a[b] for b in common], axis=-1)
    magnitude = np.sqrt(np.sum(diff ** 2, axis=-1))
    thr = otsu_threshold(magnitude[mask])
    # Guard against a degenerate cut on a scene that genuinely did not change.
    thr = float(max(thr, 0.04))
    return magnitude, thr, (magnitude > thr) & mask


def transition_matrix(
    seg_a: Segmentation,
    seg_b: Segmentation,
    mask: np.ndarray,
    pixel_area_km2: float,
    top_n: int = 8,
) -> tuple[list[dict], dict[str, dict]]:
    """Class-to-class transitions plus the net area change per class."""
    la, lb = seg_a.labels, seg_b.labels
    valid = mask & (la >= 0) & (lb >= 0)
    total = int(valid.sum())
    rows: list[dict] = []
    if total == 0:
        return rows, {}

    for i, from_c in enumerate(LANDCOVER_CLASSES):
        src = valid & (la == i)
        n_src = int(src.sum())
        if n_src == 0:
            continue
        for j, to_c in enumerate(LANDCOVER_CLASSES):
            n = int((src & (lb == j)).sum())
            if n == 0:
                continue
            rows.append({
                "from": from_c,
                "to": to_c,
                "pixels": n,
                "area_km2": round(n * pixel_area_km2, 4),
                "fraction_of_scene": round(n / total, 6),
                "is_change": from_c != to_c,
            })

    rows.sort(key=lambda r: (-int(r["is_change"]), -r["pixels"]))

    deltas: dict[str, dict] = {}
    for i, name in enumerate(LANDCOVER_CLASSES):
        n_a = int((valid & (la == i)).sum())
        n_b = int((valid & (lb == i)).sum())
        if n_a == 0 and n_b == 0:
            continue
        deltas[name] = {
            "pixels_before": n_a,
            "pixels_after": n_b,
            "delta_pixels": n_b - n_a,
            "area_before_km2": round(n_a * pixel_area_km2, 4),
            "area_after_km2": round(n_b * pixel_area_km2, 4),
            "delta_area_km2": round((n_b - n_a) * pixel_area_km2, 4),
            "fraction_before": round(n_a / total, 6),
            "fraction_after": round(n_b / total, 6),
            "relative_change_pct": (
                round((n_b - n_a) / n_a * 100.0, 2) if n_a > 0 else None
            ),
        }

    changed = [r for r in rows if r["is_change"]]
    return changed[:top_n] + [r for r in rows if not r["is_change"]][:len(LANDCOVER_CLASSES)], deltas


def analyse_change(
    bands_a: dict[str, np.ndarray],
    bands_b: dict[str, np.ndarray],
    mask: np.ndarray,
    seg_a: Segmentation | None = None,
    seg_b: Segmentation | None = None,
    pixel_area_km2: float = 0.0,
    indices: tuple[str, ...] = ("NDVI", "MNDWI", "NBR", "NDBI"),
) -> ChangeResult:
    magnitude, thr, change_mask = change_vector_analysis(bands_a, bands_b, mask)
    valid_n = int(mask.sum())
    changed_n = int(change_mask.sum())

    deltas: dict[str, np.ndarray] = {}
    delta_stats: dict[str, dict] = {}
    for name in indices:
        try:
            a = compute_index(name, bands_a)
            b = compute_index(name, bands_b)
        except KeyError:
            continue
        d = b - a
        deltas[name] = d
        vals = d[mask]
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        hist, edges = np.histogram(vals, bins=40, range=(-1.0, 1.0))
        delta_stats[name] = {
            "mean": float(vals.mean()),
            "median": float(np.median(vals)),
            "std": float(vals.std()),
            "p10": float(np.percentile(vals, 10)),
            "p90": float(np.percentile(vals, 90)),
            "fraction_increased": float((vals > 0.05).mean()),
            "fraction_decreased": float((vals < -0.05).mean()),
            "before_mean": float(a[mask][np.isfinite(a[mask])].mean()),
            "after_mean": float(b[mask][np.isfinite(b[mask])].mean()),
            "histogram": [int(v) for v in hist],
            "bin_edges": [float(v) for v in edges],
        }

    transitions: list[dict] = []
    class_deltas: dict[str, dict] = {}
    if seg_a is not None and seg_b is not None:
        transitions, class_deltas = transition_matrix(seg_a, seg_b, mask, pixel_area_km2)

    direction = None
    if "NDVI" in deltas:
        direction = deltas["NDVI"]
    elif deltas:
        direction = next(iter(deltas.values()))

    return ChangeResult(
        magnitude=magnitude,
        change_mask=change_mask,
        threshold=thr,
        changed_fraction=(changed_n / valid_n) if valid_n else 0.0,
        changed_pixels=changed_n,
        valid_pixels=valid_n,
        index_deltas=deltas,
        index_delta_stats=delta_stats,
        transitions=transitions,
        class_deltas=class_deltas,
        direction=direction,
        method=(
            f"Change Vector Analysis over {len([b for b in bands_a if b in bands_b])} common bands, "
            f"Otsu magnitude threshold {thr:.4f}"
        ),
    )


def colorise_change(
    change_mask: np.ndarray,
    direction: np.ndarray | None,
    mask: np.ndarray,
) -> np.ndarray:
    """Red = index decreased (loss), blue = index increased (gain)."""
    h, w = change_mask.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    if direction is None:
        out[change_mask] = (217, 89, 38, 210)
        return out
    loss = change_mask & (direction < 0)
    gain = change_mask & (direction >= 0)
    out[loss] = (217, 89, 38, 215)   # #d95926 decrease
    out[gain] = (57, 135, 229, 215)  # #3987e5 increase
    return out


def largest_change_regions(
    change_mask: np.ndarray,
    bbox: list[float],
    direction: np.ndarray | None = None,
    max_regions: int = 6,
    min_pixels: int = 40,
) -> list[dict]:
    """Connected components of the change mask -> geo-referenced boxes.

    This is the *where* half of "what changed and where".
    """
    from .regions import connected_components, region_boxes

    labels, n = connected_components(change_mask)
    regions = region_boxes(labels, n, bbox, min_pixels=min_pixels, max_regions=max_regions)
    if direction is not None:
        for r in regions:
            sl = (slice(r["_rows"][0], r["_rows"][1] + 1), slice(r["_cols"][0], r["_cols"][1] + 1))
            sub = direction[sl]
            sub_m = change_mask[sl]
            vals = sub[sub_m]
            if vals.size:
                mean_dir = float(vals.mean())
                r["direction"] = "increase" if mean_dir >= 0 else "decrease"
                r["mean_delta"] = round(mean_dir, 4)
    for r in regions:
        r.pop("_rows", None)
        r.pop("_cols", None)
    return regions
