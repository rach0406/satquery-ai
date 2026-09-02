"""Turn numpy results into servable artefacts: PNG overlays and chart specs.

Overlays are written once per request into ``data/cache/artifacts`` and served
statically, which keeps the JSON response small and lets Leaflet stream the
images itself.
"""
from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import settings
from ..processing.indices import CLASS_COLORS, CLASS_LABELS
from ..schemas import Artifact, Provenance

ARTIFACT_SUBDIR = "artifacts"


def artifacts_dir() -> Path:
    d = settings.cache_dir / ARTIFACT_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def save_png(arr: np.ndarray, prefix: str = "layer") -> tuple[str, str]:
    """Write an (H,W,3) or (H,W,4) array to disk; return (artifact_id, url)."""
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    mode = "RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB"
    img = Image.fromarray(arr, mode=mode)
    aid = _new_id(prefix)
    path = artifacts_dir() / f"{aid}.png"
    img.save(path, format="PNG", optimize=True)
    return aid, f"/artifacts/{aid}.png"


def png_data_uri(arr: np.ndarray) -> str:
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    mode = "RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB"
    buf = io.BytesIO()
    Image.fromarray(arr, mode=mode).save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def image_artifact(
    arr: np.ndarray,
    title: str,
    bbox: list[float] | None,
    description: str | None = None,
    provenance: Provenance | None = None,
    kind: str = "image_overlay",
    colormap: str | None = None,
    legend: list[dict] | None = None,
    prefix: str = "layer",
) -> Artifact:
    aid, url = save_png(arr, prefix)
    return Artifact(
        id=aid, kind=kind, title=title, description=description, url=url,
        bbox=bbox, provenance=provenance, colormap=colormap, legend=legend,
    )


def landcover_legend(fractions: dict[str, float]) -> list[dict]:
    rows = []
    for name, frac in sorted(fractions.items(), key=lambda kv: -kv[1]):
        if frac <= 0.0005:
            continue
        r, g, b = CLASS_COLORS.get(name, (128, 128, 128))
        rows.append({
            "key": name,
            "label": CLASS_LABELS.get(name, name),
            "color": f"rgb({r},{g},{b})",
            "value": round(frac * 100, 2),
            "unit": "%",
        })
    return rows


def ramp_legend(vmin: float, vmax: float, palette: str, unit: str = "") -> list[dict]:
    stops = {
        "rdylgn": [(178, 24, 43), (239, 138, 98), (247, 247, 247), (133, 200, 130), (26, 120, 55)],
        "blues": [(247, 251, 255), (107, 174, 214), (8, 48, 107)],
        "magma": [(0, 0, 4), (81, 18, 124), (183, 55, 121), (252, 137, 97), (252, 253, 191)],
        "coolwarm": [(59, 76, 192), (221, 221, 221), (180, 4, 38)],
        "greys": [(0, 0, 0), (255, 255, 255)],
    }.get(palette, [(0, 0, 0), (255, 255, 255)])
    n = len(stops)
    return [
        {
            "label": f"{vmin + (vmax - vmin) * i / (n - 1):.2f}{unit}",
            "color": f"rgb({r},{g},{b})",
            "value": round(vmin + (vmax - vmin) * i / (n - 1), 3),
        }
        for i, (r, g, b) in enumerate(stops)
    ]


# --------------------------------------------------------------------------
# Chart specs (rendered client-side by Plotly)
# --------------------------------------------------------------------------
def histogram_chart(
    title: str,
    counts: list[int],
    edges: list[float],
    xlabel: str,
    color: str = "#4f8cff",
    marker_lines: list[dict] | None = None,
) -> Artifact:
    centres = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
    return Artifact(
        id=_new_id("chart"),
        kind="histogram",
        title=title,
        spec={
            "type": "histogram",
            "x": centres,
            "y": counts,
            "xlabel": xlabel,
            "ylabel": "pixel count",
            "color": color,
            "markers": marker_lines or [],
            "bin_width": (edges[1] - edges[0]) if len(edges) > 1 else 0.05,
        },
    )


def bar_chart(title: str, categories: list[str], values: list[float],
              ylabel: str, colors: list[str] | None = None,
              description: str | None = None) -> Artifact:
    return Artifact(
        id=_new_id("chart"), kind="chart", title=title, description=description,
        spec={"type": "bar", "x": categories, "y": values, "ylabel": ylabel,
              "colors": colors},
    )


def grouped_bar_chart(title: str, categories: list[str],
                      series: list[dict], ylabel: str,
                      description: str | None = None) -> Artifact:
    return Artifact(
        id=_new_id("chart"), kind="chart", title=title, description=description,
        spec={"type": "grouped_bar", "x": categories, "series": series, "ylabel": ylabel},
    )


def line_chart(title: str, x: list, series: list[dict], ylabel: str,
               xlabel: str = "", description: str | None = None,
               annotations: list[dict] | None = None) -> Artifact:
    return Artifact(
        id=_new_id("chart"), kind="chart", title=title, description=description,
        spec={"type": "line", "x": x, "series": series, "ylabel": ylabel,
              "xlabel": xlabel, "annotations": annotations or []},
    )


def table_artifact(title: str, columns: list[dict], rows: list[dict],
                   description: str | None = None) -> Artifact:
    return Artifact(
        id=_new_id("table"), kind="table", title=title, description=description,
        spec={"columns": columns, "rows": rows, "row_count": len(rows)},
    )


def boxes_artifact(title: str, regions: list[dict], bbox: list[float] | None,
                   description: str | None = None,
                   provenance: Provenance | None = None) -> Artifact:
    return Artifact(
        id=_new_id("boxes"), kind="boxes", title=title, description=description,
        bbox=bbox, provenance=provenance,
        spec={"regions": regions, "count": len(regions)},
    )


def geojson_from_regions(regions: list[dict], label: str) -> dict:
    features = []
    for r in regions:
        # A region from a non-georeferenced image has no geographic box, and
        # GeoJSON has no way to express pixel coordinates honestly - so it is
        # omitted rather than emitted at a placeholder location.
        if not r.get("bbox"):
            continue
        w, s, e, n = r["bbox"]
        features.append({
            "type": "Feature",
            "properties": {
                "rank": r.get("rank"),
                "label": label,
                "area_km2": r.get("area_km2"),
                "pixels": r.get("pixels"),
                "direction": r.get("direction"),
                "centroid": r.get("centroid"),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
            },
        })
    return {"type": "FeatureCollection", "features": features,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def stamp_scene(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    """RGB scene -> RGBA with the invalid region made transparent."""
    h, w = rgb.shape[:2]
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = rgb
    out[..., 3] = 255 if alpha is None else alpha
    return out
