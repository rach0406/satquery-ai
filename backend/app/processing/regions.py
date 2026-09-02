"""Connected-component labelling and geo-referencing of regions.

Used by two features:

* **text-guided grounding** - "highlight the water body in this image" resolves
  to a class mask, whose components become geo-referenced boxes; and
* **change localisation** - "where did the change occur" turns the change mask
  into ranked regions with real areas and centroids.

SciPy's labeller is used when available (it is in requirements) and a compact
union-find implementation is kept as a fallback so the module never hard-fails.
"""
from __future__ import annotations

import numpy as np


def connected_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 8-connected components of a boolean mask."""
    try:
        from scipy import ndimage

        structure = np.ones((3, 3), dtype=bool)
        labels, n = ndimage.label(mask, structure=structure)
        return labels.astype(np.int32), int(n)
    except Exception:
        return _components_fallback(mask)


def _components_fallback(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Two-pass union-find labelling (no SciPy required)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent: list[int] = [0]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    nxt = 1
    for y in range(h):
        for x in range(w):
            if not mask[y, x]:
                continue
            neigh = []
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
                ny, nx_ = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx_ < w and labels[ny, nx_]:
                    neigh.append(int(labels[ny, nx_]))
            if not neigh:
                labels[y, x] = nxt
                parent.append(nxt)
                nxt += 1
            else:
                m = min(neigh)
                labels[y, x] = m
                for nb in neigh:
                    union(m, nb)

    remap: dict[int, int] = {}
    out = np.zeros_like(labels)
    count = 0
    nz = np.nonzero(labels)
    for y, x in zip(*nz):
        root = find(int(labels[y, x]))
        if root not in remap:
            count += 1
            remap[root] = count
        out[y, x] = remap[root]
    return out, count


def pixel_to_lonlat(bbox: list[float], shape: tuple[int, int], row: float, col: float
                    ) -> tuple[float, float]:
    """Row/col (origin top-left) -> lon/lat for a north-up EPSG:4326 grid."""
    w, s, e, n = bbox
    h, wd = shape
    lon = w + (col + 0.5) / wd * (e - w)
    lat = n - (row + 0.5) / h * (n - s)
    return float(lon), float(lat)


def region_location(region: dict) -> str:
    """Human-readable position of a region, in whichever space it is known.

    Geographic when the scene was georeferenced, pixel coordinates otherwise.
    Never invents a longitude/latitude.
    """
    if region.get("georeferenced") and region.get("centroid"):
        lon, lat = region["centroid"]
        return f"{lon:.4f}, {lat:.4f}"
    cx, cy = region.get("pixel_centroid", [0, 0])
    return f"pixel {cx:.0f}, {cy:.0f}"


def region_extent(region: dict) -> str:
    """Bounding box of a region as text, geographic or pixel."""
    if region.get("georeferenced") and region.get("bbox"):
        return ", ".join(f"{v:.3f}" for v in region["bbox"])
    c0, r0, c1, r1 = region["pixel_bbox"]
    return f"x {c0}-{c1}, y {r0}-{r1} px"


def region_size(region: dict, georeferenced: bool) -> float:
    """Region size in km² when located, pixel count otherwise."""
    if georeferenced and "area_km2" in region:
        return region["area_km2"]
    return region["pixels"]


def region_boxes(
    labels: np.ndarray,
    n_labels: int,
    bbox: list[float] | None,
    min_pixels: int = 30,
    max_regions: int = 8,
) -> list[dict]:
    """Rank components by pixel count and geo-reference their bounding boxes.

    ``bbox`` may be ``None`` for an image with no georeferencing. In that case
    the regions are returned in **pixel space only** - no ``bbox``, no
    ``centroid``, no ``area_km2``. Substituting a placeholder extent here would
    emit real-looking longitudes and latitudes off the coast of West Africa for
    an image that was never located, which is exactly the kind of invented
    number the rest of this system exists to prevent.
    """
    if n_labels == 0:
        return []
    h, w = labels.shape
    total_px = h * w
    georeferenced = bbox is not None
    px_area = 0.0
    if georeferenced:
        from ..datasources.gazetteer import bbox_area_km2

        px_area = bbox_area_km2(tuple(bbox)) / max(total_px, 1)

    counts = np.bincount(labels.ravel())
    order = np.argsort(counts)[::-1]
    out: list[dict] = []
    for lid in order:
        if lid == 0:
            continue
        npx = int(counts[lid])
        if npx < min_pixels:
            break
        ys, xs = np.nonzero(labels == lid)
        r0, r1 = int(ys.min()), int(ys.max())
        c0, c1 = int(xs.min()), int(xs.max())
        cy, cx = float(ys.mean()), float(xs.mean())
        box_px = max((r1 - r0 + 1) * (c1 - c0 + 1), 1)
        row: dict = {
            "rank": len(out) + 1,
            "pixels": npx,
            "fraction_of_scene": round(npx / total_px, 6),
            "pixel_bbox": [c0, r0, c1, r1],
            "pixel_centroid": [round(cx, 1), round(cy, 1)],
            "fill_ratio": round(npx / box_px, 4),
            "georeferenced": georeferenced,
            "_rows": (r0, r1),
            "_cols": (c0, c1),
        }
        if georeferenced:
            lon_w, lat_n = pixel_to_lonlat(bbox, (h, w), r0, c0)
            lon_e, lat_s = pixel_to_lonlat(bbox, (h, w), r1, c1)
            clon, clat = pixel_to_lonlat(bbox, (h, w), cy, cx)
            row["area_km2"] = round(npx * px_area, 4)
            row["bbox"] = [round(lon_w, 5), round(lat_s, 5),
                           round(lon_e, 5), round(lat_n, 5)]
            row["centroid"] = [round(clon, 5), round(clat, 5)]
        out.append(row)
        if len(out) >= max_regions:
            break
    return out


def clean_mask(mask: np.ndarray, min_size: int = 12, closing: int = 1) -> np.ndarray:
    """Remove speckle so grounding boxes track real objects, not noise."""
    try:
        from scipy import ndimage

        m = mask
        if closing > 0:
            st = np.ones((2 * closing + 1, 2 * closing + 1), dtype=bool)
            m = ndimage.binary_closing(m, structure=st)
            m = ndimage.binary_opening(m, structure=st)
        labels, n = ndimage.label(m, structure=np.ones((3, 3), dtype=bool))
        if n == 0:
            return m
        counts = np.bincount(labels.ravel())
        keep = np.isin(labels, np.nonzero(counts >= min_size)[0])
        keep[labels == 0] = False
        return keep
    except Exception:
        return mask
