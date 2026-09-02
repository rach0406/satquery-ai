"""Inference wrapper for the remote-sensing-adapted scene classifier.

Loads the artefact produced by :mod:`app.ml.train_eurosat` once and serves
tile-wise predictions. If the model has not been trained yet the wrapper
reports itself unavailable - the agent then routes around it and says so in
the execution trace, rather than silently guessing.
"""
from __future__ import annotations

import json
import pickle
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..config import settings
from .features import extract_batch, tile_image

MODEL_FILE = "eurosat_rs_classifier.pkl"
REPORT_FILE = "eurosat_rs_classifier.report.json"

_lock = threading.Lock()
_state: dict[str, Any] = {"loaded": False, "bundle": None, "report": None, "error": None}


def _load() -> None:
    if _state["loaded"]:
        return
    with _lock:
        if _state["loaded"]:
            return
        path = settings.models_dir / MODEL_FILE
        rep = settings.models_dir / REPORT_FILE
        try:
            if not path.exists():
                raise FileNotFoundError(
                    "Remote-sensing classifier not trained yet. "
                    "Run: python -m app.ml.train_eurosat"
                )
            with open(path, "rb") as f:
                _state["bundle"] = pickle.load(f)
            if rep.exists():
                _state["report"] = json.loads(rep.read_text(encoding="utf-8"))
            _state["error"] = None
        except Exception as exc:
            _state["bundle"] = None
            _state["error"] = str(exc)
        _state["loaded"] = True


def is_available() -> bool:
    _load()
    return _state["bundle"] is not None


def load_error() -> str | None:
    _load()
    return _state["error"]


def model_info() -> dict:
    """Everything the UI shows about the adapted model, straight from training."""
    _load()
    rep = _state["report"] or {}
    return {
        "available": _state["bundle"] is not None,
        "error": _state["error"],
        "name": rep.get("model", "eurosat_rs_classifier"),
        "version": rep.get("version", "1.0.0"),
        "backend": rep.get("backend"),
        "adapted_on": rep.get("adapted_on"),
        "dataset_url": rep.get("dataset_url"),
        "citation": rep.get("citation"),
        "classes": rep.get("classes", []),
        "class_descriptions": rep.get("class_descriptions", {}),
        "test_accuracy": rep.get("test_accuracy"),
        "macro_f1": rep.get("macro_f1"),
        "per_class": rep.get("per_class", {}),
        "confusion_matrix": rep.get("confusion_matrix"),
        "n_train": rep.get("n_train"),
        "n_test": rep.get("n_test"),
        "n_features": rep.get("n_features"),
        "trained_at": rep.get("trained_at"),
        "evaluation_protocol": rep.get("evaluation_protocol"),
    }


def classes() -> list[str]:
    _load()
    b = _state["bundle"]
    return list(b["classes"]) if b else []


def coarse_map() -> dict[str, str]:
    _load()
    b = _state["bundle"]
    return dict(b["coarse_map"]) if b else {}


def predict_patches(patches: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (class indices, per-patch max probability)."""
    _load()
    b = _state["bundle"]
    if b is None:
        raise RuntimeError(_state["error"] or "classifier unavailable")
    if len(patches) == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=float)
    X = extract_batch(patches)
    Xs = b["scaler"].transform(X)
    proba = b["classifier"].predict_proba(Xs)
    return proba.argmax(axis=1), proba.max(axis=1)


def classify_scene(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
    tile: int = 64,
    stride: int = 64,
    max_tiles: int = 900,
) -> dict:
    """Tile-wise land-use classification of a whole scene.

    Returns the dominant class, the full class distribution weighted by tile
    count, a per-tile label grid for map rendering, and mean confidence -
    every one of which is measured, not asserted.
    """
    _load()
    b = _state["bundle"]
    if b is None:
        raise RuntimeError(_state["error"] or "classifier unavailable")

    patches, coords = tile_image(rgb, tile=tile, stride=stride, mask=mask, min_valid=0.6)
    if len(patches) == 0:
        return {
            "status": "no_data",
            "message": "No fully valid tile of the requested size fits inside the observed area.",
            "tiles": 0,
        }
    if len(patches) > max_tiles:
        sel = np.linspace(0, len(patches) - 1, max_tiles).astype(int)
        patches, coords = patches[sel], [coords[i] for i in sel]

    idx, conf = predict_patches(patches)
    names = b["classes"]
    cmap = b["coarse_map"]

    counts: dict[str, int] = {}
    conf_sum: dict[str, float] = {}
    for i, c in zip(idx, conf):
        n = names[int(i)]
        counts[n] = counts.get(n, 0) + 1
        conf_sum[n] = conf_sum.get(n, 0.0) + float(c)

    total = int(len(idx))
    distribution = [
        {
            "class": n,
            "coarse_class": cmap.get(n, "unclassified"),
            "tiles": counts[n],
            "fraction": round(counts[n] / total, 4),
            "mean_confidence": round(conf_sum[n] / counts[n], 4),
            "description": b["class_descriptions"].get(n, ""),
        }
        for n in sorted(counts, key=lambda k: -counts[k])
    ]

    coarse_counts: dict[str, int] = {}
    for n, c in counts.items():
        k = cmap.get(n, "unclassified")
        coarse_counts[k] = coarse_counts.get(k, 0) + c

    return {
        "status": "ok",
        "tiles": total,
        "tile_size_px": tile,
        "dominant_class": distribution[0]["class"],
        "dominant_fraction": distribution[0]["fraction"],
        "distribution": distribution,
        "coarse_distribution": {
            k: round(v / total, 4) for k, v in sorted(coarse_counts.items(), key=lambda kv: -kv[1])
        },
        "mean_confidence": round(float(conf.mean()), 4),
        "min_confidence": round(float(conf.min()), 4),
        "labels": [
            {"row": int(r), "col": int(c), "class": names[int(i)], "confidence": round(float(p), 3)}
            for (r, c), i, p in zip(coords, idx, conf)
        ],
    }


def label_grid(result: dict, shape: tuple[int, int], tile: int = 64) -> np.ndarray:
    """Paint tile predictions back onto a full-resolution label image."""
    from ..processing.indices import LANDCOVER_CLASSES

    h, w = shape
    out = np.full((h, w), -1, dtype=np.int16)
    cmap = coarse_map()
    for lab in result.get("labels", []):
        coarse = cmap.get(lab["class"], "unclassified")
        if coarse not in LANDCOVER_CLASSES:
            continue
        ci = LANDCOVER_CLASSES.index(coarse)
        r, c = lab["row"], lab["col"]
        out[r:r + tile, c:c + tile] = ci
    return out
