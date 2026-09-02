"""Remote-sensing feature extraction for the scene-classification head.

The problem statement requires at least one visual component *adapted to
remote-sensing imagery* rather than a generic ImageNet model applied blind.
This module defines the representation that adaptation is performed on:
spectral statistics, vegetation/water/soil index moments, texture energy and
a coarse spatial layout descriptor - all computed on real Sentinel-2 patches.

The design is deliberately CPU-only and dependency-light so the model trains
in minutes on a laptop and loads instantly during a live demo. When PyTorch is
present the trainer swaps in a small CNN over the same patches; the feature
extractor below remains the guaranteed-available path.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-6

#: Order matters - it defines the feature vector layout.
CHANNELS = ("red", "green", "blue")
PERCENTILES = (5, 25, 50, 75, 95)
HIST_BINS = 12


def _safe_nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b) / np.maximum(a + b, EPS)


def _moments(v: np.ndarray, prefix: str) -> tuple[list[float], list[str]]:
    v = v[np.isfinite(v)]
    if v.size == 0:
        return [0.0] * (4 + len(PERCENTILES)), [
            f"{prefix}_{n}" for n in ("mean", "std", "skew", "kurt", *[f"p{p}" for p in PERCENTILES])
        ]
    mean = float(v.mean())
    std = float(v.std())
    z = (v - mean) / max(std, EPS)
    vals = [mean, std, float((z ** 3).mean()), float((z ** 4).mean())]
    vals += [float(x) for x in np.percentile(v, PERCENTILES)]
    names = [f"{prefix}_{n}" for n in ("mean", "std", "skew", "kurt", *[f"p{p}" for p in PERCENTILES])]
    return vals, names


def _gradient_energy(g: np.ndarray) -> tuple[float, float, float]:
    gy, gx = np.gradient(g)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    return float(mag.mean()), float(mag.std()), float(np.percentile(mag, 95))


def _sat(p: np.ndarray) -> np.ndarray:
    """Summed-area table with a zero row/column prepended.

    ``S[i, j] = sum(p[:i, :j])`` so a k-box sum is a clean 4-term lookup with
    no off-by-one at the edges.
    """
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    return np.pad(c, ((1, 0), (1, 0)), mode="constant")


def _local_std(g: np.ndarray, k: int) -> np.ndarray:
    """Box-filter local standard deviation, SciPy-free."""
    h, w = g.shape
    pad = k // 2
    p = np.pad(g, pad, mode="reflect")
    s1, s2 = _sat(p), _sat(p ** 2)

    def box(s: np.ndarray) -> np.ndarray:
        return s[k:k + h, k:k + w] - s[0:h, k:k + w] - s[k:k + h, 0:w] + s[0:h, 0:w]

    n = float(k * k)
    m = box(s1) / n
    m2 = box(s2) / n
    return np.sqrt(np.maximum(m2 - m ** 2, 0.0))


def extract_features(patch: np.ndarray) -> np.ndarray:
    """Feature vector for one RGB patch given as uint8 or float 0..1."""
    return _extract(patch)[0]


def feature_names(patch_shape: tuple[int, int] = (64, 64)) -> list[str]:
    dummy = np.zeros((*patch_shape, 3), dtype=np.float32)
    return _extract(dummy)[1]


def _extract(patch: np.ndarray) -> tuple[np.ndarray, list[str]]:
    a = patch.astype(np.float32)
    if a.max() > 1.5:
        a = a / 255.0
    if a.ndim == 2:
        a = np.stack([a] * 3, axis=-1)
    a = a[..., :3]

    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gray = a.mean(axis=2)

    vals: list[float] = []
    names: list[str] = []

    # --- per-channel spectral moments ------------------------------------
    for name, ch in zip(CHANNELS, (r, g, b)):
        v, n = _moments(ch, name)
        vals += v
        names += n

    # --- RGB-only vegetation / soil / water proxies -----------------------
    total = np.maximum(r + g + b, EPS)
    derived = {
        "vari": _safe_nd(g, r) if True else None,          # greenness
        "exg": 2 * g - r - b,                              # excess green
        "gli": (2 * g - r - b) / np.maximum(2 * g + r + b, EPS),
        "ngrdi": _safe_nd(g, r),
        "rbdiff": _safe_nd(r, b),
        "chroma_r": r / total,
        "chroma_g": g / total,
        "chroma_b": b / total,
        "brightness": gray,
        "saturation": (a.max(axis=2) - a.min(axis=2)) / np.maximum(a.max(axis=2), EPS),
    }
    for key, arr in derived.items():
        v, n = _moments(arr, key)
        vals += v
        names += n

    # --- texture ----------------------------------------------------------
    for k in (3, 7, 15):
        ls = _local_std(gray, k)
        vals += [float(ls.mean()), float(ls.std()), float(np.percentile(ls, 90))]
        names += [f"texstd{k}_mean", f"texstd{k}_std", f"texstd{k}_p90"]

    gm, gs, gp = _gradient_energy(gray)
    vals += [gm, gs, gp]
    names += ["grad_mean", "grad_std", "grad_p95"]

    edge_density = float((np.abs(np.gradient(gray)[0]) + np.abs(np.gradient(gray)[1]) > 0.06).mean())
    vals.append(edge_density)
    names.append("edge_density")

    # --- colour histograms ------------------------------------------------
    for name, ch in zip(CHANNELS, (r, g, b)):
        hist, _ = np.histogram(ch, bins=HIST_BINS, range=(0.0, 1.0))
        hist = hist.astype(np.float32) / max(ch.size, 1)
        vals += [float(x) for x in hist]
        names += [f"hist_{name}_{i}" for i in range(HIST_BINS)]

    # --- coarse spatial layout (3x3 grid means) ---------------------------
    h, w = gray.shape
    for gi in range(3):
        for gj in range(3):
            ys = slice(gi * h // 3, (gi + 1) * h // 3)
            xs = slice(gj * w // 3, (gj + 1) * w // 3)
            cell = a[ys, xs]
            if cell.size == 0:
                vals += [0.0, 0.0, 0.0]
            else:
                vals += [float(cell[..., c].mean()) for c in range(3)]
            names += [f"grid{gi}{gj}_{c}" for c in CHANNELS]

    # --- global structure -------------------------------------------------
    row_var = float(gray.mean(axis=1).std())
    col_var = float(gray.mean(axis=0).std())
    vals += [row_var, col_var, float(abs(row_var - col_var))]
    names += ["row_profile_std", "col_profile_std", "anisotropy"]

    out = np.asarray(vals, dtype=np.float32)
    out[~np.isfinite(out)] = 0.0
    return out, names


def extract_batch(patches: np.ndarray | list[np.ndarray]) -> np.ndarray:
    return np.stack([extract_features(p) for p in patches])


def tile_image(
    img: np.ndarray,
    tile: int = 64,
    stride: int | None = None,
    mask: np.ndarray | None = None,
    min_valid: float = 0.6,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Cut an image into patches for tile-wise classification.

    Returns the patch stack and the top-left pixel coordinate of each patch, so
    predictions can be painted back onto the map at the right place.
    """
    stride = stride or tile
    h, w = img.shape[:2]
    patches: list[np.ndarray] = []
    coords: list[tuple[int, int]] = []
    for y in range(0, max(h - tile + 1, 1), stride):
        for x in range(0, max(w - tile + 1, 1), stride):
            sub = img[y:y + tile, x:x + tile]
            if sub.shape[0] < tile or sub.shape[1] < tile:
                continue
            if mask is not None and mask[y:y + tile, x:x + tile].mean() < min_valid:
                continue
            patches.append(sub)
            coords.append((y, x))
    if not patches:
        return np.empty((0, tile, tile, 3), dtype=img.dtype), []
    return np.stack(patches), coords
