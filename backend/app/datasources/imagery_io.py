"""Scene ingestion: uploads, bundled samples, metadata and compatibility.

The problem statement makes "check the number, modality, format, metadata and
compatibility of the input images" an explicit controller duty, so this module
does that work properly rather than trusting a filename.

GeoTIFF handling degrades gracefully: rasterio is used when installed (full
CRS/transform/band awareness), otherwise Pillow reads the TIFF pixels and we
report that georeferencing was unavailable instead of inventing a transform.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..config import settings
from ..schemas import DataOrigin, Provenance

SUPPORTED_EXT = {".tif", ".tiff", ".geotiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
GEO_EXT = {".tif", ".tiff", ".geotiff"}

#: Longest side we will analyse. A 6000 x 4800 phone photo is 28.8 megapixels;
#: held as float32 bands that is hundreds of megabytes for no analytical gain,
#: because every downstream threshold is computed on distributions rather than
#: on fine detail. Larger images are decimated and the factor is reported.
MAX_ANALYSIS_SIDE = 2048

#: Refuse absurd images outright rather than trying to decimate them. Pillow's
#: own decompression-bomb guard sits above this; this is the analysis budget.
MAX_TOTAL_PIXELS = 120_000_000


class ImageLoadError(ValueError):
    """The file could not be read as an image. Message is user-facing."""

try:  # optional
    import rasterio  # type: ignore
    from rasterio.warp import transform_bounds  # type: ignore

    HAS_RASTERIO = True
except Exception:  # pragma: no cover - optional dependency
    rasterio = None  # type: ignore
    HAS_RASTERIO = False


def _INDEX_REQUIREMENTS() -> dict:
    from ..processing.indices import INDEX_REQUIREMENTS

    return INDEX_REQUIREMENTS


def _unavailable_reasons(has_ms: bool, has_rgb: bool, geo: bool) -> list[dict]:
    """Features this scene genuinely cannot support, each with a plain reason.

    Only true blockers appear here. Missing georeferencing disables the small
    set of operations that need a position on Earth - it does not disable image
    analysis, and nothing in this list is an error message.
    """
    out: list[dict] = []
    if not geo:
        out.append({
            "feature": "Area in km²",
            "reason": "The image has no map projection, so pixels cannot be converted to "
                      "ground distance. Sizes are reported in pixels instead.",
        })
        out.append({
            "feature": "Map overlay placement",
            "reason": "Results cannot be drawn on a world map without coordinates. The "
                      "rendered layers are still produced and viewable.",
        })
        out.append({
            "feature": "Archive comparison (change detection, time series)",
            "reason": "Fetching matching satellite imagery for another date requires knowing "
                      "where on Earth the image is.",
        })
    if not has_ms:
        out.append({
            "feature": "NDVI, NDWI, MNDWI, NBR, NDBI",
            "reason": "These need a near-infrared or shortwave-infrared band. A visible-only "
                      "image supports VARI instead.",
        })
    if not has_rgb:
        out.append({
            "feature": "Scene classification",
            "reason": "The EuroSAT-adapted classifier expects a red/green/blue image.",
        })
    return out


#: How we guess band semantics from band count when the file does not say.
BAND_PRESETS: dict[int, tuple[str, ...]] = {
    1: ("gray",),
    2: ("vv", "vh"),
    3: ("red", "green", "blue"),
    4: ("red", "green", "blue", "nir"),
    5: ("blue", "green", "red", "nir", "swir2"),
    6: ("blue", "green", "red", "nir", "swir1", "swir2"),
}


@dataclass
class Scene:
    """One analysable image, whether uploaded, bundled or fetched."""

    scene_id: str
    name: str
    array: np.ndarray                    # (H, W, C) uint8 display representation
    bands: dict[str, np.ndarray]         # semantic band name -> float 0..1
    valid_mask: np.ndarray
    modality: str                        # optical | multispectral | sar | derived
    bbox: list[float] | None
    acquisition_date: str | None
    provenance: Provenance
    metadata: dict[str, Any] = field(default_factory=dict)
    thumbnail_url: str | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape[0], self.array.shape[1]

    @property
    def georeferenced(self) -> bool:
        return self.bbox is not None

    @property
    def spatial_reference(self) -> str:
        """``"georeferenced"`` or ``"pixel_space"``.

        Both are valid, fully analysable states. Pixel space is not an error
        and not a degraded load - it simply means the file carried no map
        projection, which is true of every ordinary photograph.
        """
        return "georeferenced" if self.bbox is not None else "pixel_space"

    def capabilities(self) -> dict:
        """What this scene can and cannot support, and why.

        The UI uses this to enable or explain features instead of guessing, and
        the controller uses it to skip geo-only tools with a real reason.
        """
        has_ms = all(b in self.bands for b in ("nir", "red"))
        has_rgb = all(b in self.bands for b in ("red", "green", "blue"))
        geo = self.georeferenced
        return {
            "spatial_reference": self.spatial_reference,
            "band_basis": "multispectral" if has_ms else ("rgb" if has_rgb else "single_band"),
            "available": {
                "land_cover_segmentation": has_ms or has_rgb,
                "scene_classification": has_rgb,
                "region_grounding": has_ms or has_rgb,
                "captioning": True,
                "visual_question_answering": True,
                "spectral_indices": sorted(
                    k for k, need in _INDEX_REQUIREMENTS().items()
                    if all(b in self.bands for b in need)),
            },
            "unavailable": _unavailable_reasons(has_ms, has_rgb, geo),
        }

    def summary(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "modality": self.modality,
            "width": self.shape[1],
            "height": self.shape[0],
            "bands": sorted(self.bands.keys()),
            "band_count": len(self.bands),
            "bbox": self.bbox,
            "georeferenced": self.georeferenced,
            "spatial_reference": self.spatial_reference,
            "capabilities": self.capabilities(),
            "acquisition_date": self.acquisition_date,
            "origin": self.provenance.origin.value,
            "is_real": self.provenance.is_real,
            "source": self.provenance.source,
            "valid_fraction": round(float(self.valid_mask.mean()), 4),
            "thumbnail_url": self.thumbnail_url,
            "metadata": self.metadata,
        }


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _normalise_band(a: np.ndarray) -> np.ndarray:
    """Scale any dtype to 0..1 using a robust 2-98 percentile stretch."""
    a = a.astype(np.float32)
    finite = np.isfinite(a)
    if not finite.any():
        return np.zeros_like(a)
    if a.dtype == np.uint8 or (a[finite].min() >= 0 and a[finite].max() <= 255 and a[finite].max() > 1.5):
        lo, hi = 0.0, 255.0
    else:
        lo, hi = np.percentile(a[finite], [2, 98])
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def _infer_modality(band_names: tuple[str, ...], n_bands: int, filename: str) -> str:
    lower = filename.lower()
    if any(t in lower for t in ("sar", "s1", "sentinel1", "sentinel-1", "risat", "grd", "rtc")):
        return "sar"
    if set(band_names) & {"vv", "vh", "hh", "hv"}:
        return "sar"
    if n_bands == 1:
        return "sar" if "sar" in lower else "derived"
    if n_bands >= 4:
        return "multispectral"
    return "optical"


def load_scene_file(
    path: Path,
    scene_id: str | None = None,
    origin: DataOrigin = DataOrigin.USER_UPLOAD,
    name: str | None = None,
    declared_modality: str | None = None,
    bbox: list[float] | None = None,
    acquisition_date: str | None = None,
    source: str | None = None,
) -> Scene:
    """Read an image file into a :class:`Scene`, extracting real metadata."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ImageLoadError(
            f"'{ext or path.name}' is not a supported image format. Accepted: "
            "GeoTIFF/TIFF (geospatial), PNG, JPEG, BMP or WebP (ordinary images)."
        )
    if not path.exists() or path.stat().st_size == 0:
        raise ImageLoadError(f"'{path.name}' is empty or could not be found.")

    meta: dict[str, Any] = {
        "filename": path.name,
        "format": ext.lstrip("."),
        "size_bytes": path.stat().st_size,
        "sha1": hashlib.sha1(path.read_bytes()).hexdigest()[:16],
    }
    arr_stack: np.ndarray | None = None
    band_names: tuple[str, ...] | None = None
    crs = "EPSG:4326"

    if ext in GEO_EXT and HAS_RASTERIO:
        try:
            # An ordinary TIFF legitimately has no geotransform; rasterio warns
            # about it, but here that is an expected, handled case rather than
            # a problem worth surfacing in the server log.
            import warnings as _warnings

            from rasterio.errors import NotGeoreferencedWarning  # type: ignore

            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore", NotGeoreferencedWarning)
                ds_cm = rasterio.open(path)  # type: ignore[union-attr]
        except Exception as exc:
            raise ImageLoadError(
                f"'{path.name}' could not be opened as a TIFF/GeoTIFF: {exc}"
            ) from exc
        with ds_cm as ds:
            if ds.width * ds.height > MAX_TOTAL_PIXELS:
                raise ImageLoadError(
                    f"'{path.name}' is {ds.width}x{ds.height} "
                    f"({ds.width * ds.height / 1e6:.0f} megapixels), which is beyond the "
                    f"{MAX_TOTAL_PIXELS / 1e6:.0f} MP analysis limit. Crop or downsample it "
                    "first."
                )
            # Decimated read: rasterio resamples on the way in, so a large
            # GeoTIFF never lands in memory at full resolution.
            dec = max(1, int(np.ceil(max(ds.width, ds.height) / MAX_ANALYSIS_SIDE)))
            out_h, out_w = ds.height // dec, ds.width // dec
            arr_stack = ds.read(out_shape=(ds.count, max(out_h, 1), max(out_w, 1)))
            arr_stack = np.moveaxis(arr_stack, 0, -1)   # (H, W, C)
            if dec > 1:
                meta["decimation_factor"] = dec
                meta["original_size"] = [ds.width, ds.height]
            meta.update({
                "driver": ds.driver,
                "dtype": str(ds.dtypes[0]),
                "band_count": ds.count,
                "nodata": ds.nodata,
                "crs": str(ds.crs) if ds.crs else None,
                "transform": list(ds.transform)[:6] if ds.transform else None,
                # A TIFF read through rasterio is not necessarily georeferenced.
                # Without a CRS rasterio hands back an identity transform, which
                # must not be mistaken for a real map projection.
                "georeferencing": (
                    "read from file (rasterio)" if ds.crs else
                    "none - this TIFF carries no CRS, so it is an ordinary image"
                ),
            })
            if ds.crs and bbox is None:
                try:
                    w, s, e, n = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)  # type: ignore
                    bbox = [float(w), float(s), float(e), float(n)]
                    crs = str(ds.crs)
                except Exception:
                    bbox = None
            desc = [d for d in (ds.descriptions or []) if d]
            if desc and len(desc) == ds.count:
                meta["band_descriptions"] = list(desc)
                mapped = tuple(_map_band_name(d) for d in desc)
                if all(mapped):
                    band_names = mapped  # type: ignore[assignment]
            tags = ds.tags()
            if tags:
                meta["tiff_tags"] = {k: v for k, v in list(tags.items())[:20]}
                for key in ("ACQUISITION_DATE", "TIFFTAG_DATETIME", "DATE", "acquisition_date"):
                    if key in tags and acquisition_date is None:
                        acquisition_date = str(tags[key])[:10]
                        break
    else:
        try:
            img = Image.open(path)
            img.load()          # force a full decode so truncation surfaces here
        except Image.DecompressionBombError as exc:
            raise ImageLoadError(
                f"'{path.name}' is too large to open safely: {exc}"
            ) from exc
        except (OSError, SyntaxError, ValueError) as exc:
            raise ImageLoadError(
                f"'{path.name}' could not be read as an image - the file appears to be "
                f"corrupted, truncated or not actually a {ext.lstrip('.') or 'image'} "
                f"file. ({type(exc).__name__}: {exc})"
            ) from exc

        meta.update({
            "pillow_mode": img.mode,
            "georeferencing": (
                "rasterio is installed but this TIFF carries no CRS" if ext in GEO_EXT
                and HAS_RASTERIO else
                "rasterio not installed" if ext in GEO_EXT else
                "not applicable - ordinary image format"
            ),
        })
        if img.width * img.height > MAX_TOTAL_PIXELS:
            raise ImageLoadError(
                f"'{path.name}' is {img.width}x{img.height} "
                f"({img.width * img.height / 1e6:.0f} megapixels), beyond the "
                f"{MAX_TOTAL_PIXELS / 1e6:.0f} MP analysis limit."
            )
        if getattr(img, "n_frames", 1) > 1:
            meta["frames"] = img.n_frames

        # Decimate large images before they become float band arrays.
        longest = max(img.width, img.height)
        if longest > MAX_ANALYSIS_SIDE:
            scale = MAX_ANALYSIS_SIDE / longest
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            meta["original_size"] = [img.width, img.height]
            meta["resampled_to"] = list(new_size)
            img = img.resize(new_size, Image.Resampling.BILINEAR)

        if img.mode in ("I;16", "I", "F"):
            arr_stack = np.array(img)[..., None]
        elif img.mode in ("L", "LA"):
            # A genuinely single-channel image stays single-channel. Widening it
            # to RGB would report three bands that carry one band of information.
            meta["single_channel"] = True
            a = np.array(img)
            if img.mode == "LA":
                meta["has_alpha"] = True
                meta["_alpha"] = a[..., 1]
                arr_stack = a[..., 0][..., None]
            else:
                arr_stack = a[..., None]
        else:
            img = img.convert("RGBA") if "A" in img.mode else img.convert("RGB")
            a = np.array(img)
            if a.shape[-1] == 4:
                meta["has_alpha"] = True
            arr_stack = a
        meta["band_count"] = arr_stack.shape[-1]
        try:
            exif = getattr(img, "_getexif", lambda: None)()
            if exif:
                meta["exif_keys"] = len(exif)
        except Exception:
            pass

    if arr_stack is None or arr_stack.size == 0:
        raise ValueError(f"Could not read any pixels from {path.name}.")
    if arr_stack.ndim == 2:
        arr_stack = arr_stack[..., None]

    n_bands = arr_stack.shape[-1]
    alpha: np.ndarray | None = meta.pop("_alpha", None)
    if n_bands == 4 and meta.get("has_alpha"):
        alpha = arr_stack[..., 3]
        arr_stack = arr_stack[..., :3]
        n_bands = 3

    if band_names is None:
        band_names = BAND_PRESETS.get(n_bands, tuple(f"band_{i + 1}" for i in range(n_bands)))
    meta["band_mapping"] = list(band_names)
    meta["band_mapping_source"] = "file metadata" if meta.get("band_descriptions") else "inferred from band count"

    bands: dict[str, np.ndarray] = {}
    for i, bname in enumerate(band_names[:n_bands]):
        bands[bname] = _normalise_band(arr_stack[..., i])

    # A single-band SAR/derived product still needs an RGB rendering.
    if n_bands >= 3 and set(band_names[:3]) >= {"red", "green", "blue"}:
        rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    else:
        base = bands[band_names[0]]
        rgb = np.stack([base, base, base], axis=-1)
    display = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)

    if alpha is not None:
        valid = alpha > 10
    else:
        nodata = meta.get("nodata")
        if nodata is not None:
            valid = ~np.all(arr_stack == nodata, axis=-1)
        else:
            valid = np.ones(display.shape[:2], dtype=bool)

    modality = declared_modality or _infer_modality(tuple(band_names), n_bands, path.name)
    scene_id = scene_id or f"up_{uuid.uuid4().hex[:10]}"

    prov = Provenance(
        origin=origin,
        source=source or (
            "User-uploaded imagery" if origin is DataOrigin.USER_UPLOAD else "Bundled sample scene"
        ),
        source_url=None,
        modality=modality,  # type: ignore[arg-type]
        acquisition_date=acquisition_date,
        bbox=bbox,
        crs=crs,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=(
            None if bbox else
            "Ordinary image with no map projection. Image analysis runs normally; "
            "sizes are reported in pixels rather than km²."
        ),
    )
    return Scene(
        scene_id=scene_id, name=name or path.stem, array=display, bands=bands,
        valid_mask=valid, modality=modality, bbox=bbox,
        acquisition_date=acquisition_date, provenance=prov, metadata=meta,
    )


def _map_band_name(desc: str) -> str | None:
    d = desc.strip().lower()
    table = {
        "blue": "blue", "b2": "blue", "b02": "blue",
        "green": "green", "b3": "green", "b03": "green",
        "red": "red", "b4": "red", "b04": "red",
        "nir": "nir", "b8": "nir", "b08": "nir", "near infrared": "nir",
        "swir": "swir2", "swir1": "swir1", "b11": "swir1",
        "swir2": "swir2", "b12": "swir2",
        "vv": "vv", "vh": "vh", "hh": "hh", "hv": "hv",
    }
    return table.get(d)


# --------------------------------------------------------------------------
# Compatibility checking - an explicit controller duty in the PS
# --------------------------------------------------------------------------
def check_pair_compatibility(a: Scene, b: Scene) -> dict:
    """Can these two scenes legitimately be compared? Report, do not assume."""
    issues: list[str] = []
    warnings: list[str] = []

    same_shape = a.shape == b.shape
    if not same_shape:
        issues.append(
            f"Raster grids differ ({a.shape[1]}x{a.shape[0]} vs {b.shape[1]}x{b.shape[0]}); "
            "the pair must be resampled to a common grid before pixel-wise comparison."
        )

    geo_ok = False
    offset = None
    if a.bbox and b.bbox:
        offset = max(abs(x - y) for x, y in zip(a.bbox, b.bbox))
        geo_ok = offset < 1e-4
        if not geo_ok:
            issues.append(
                f"Geographic extents differ by up to {offset:.5f} deg - the scenes do not "
                "cover the same ground area."
            )
    elif a.bbox or b.bbox:
        warnings.append("Only one scene is georeferenced; co-registration cannot be verified.")
    else:
        warnings.append("Neither scene is georeferenced; assuming pixel-space alignment.")

    shared = sorted(set(a.bands) & set(b.bands))
    if not shared:
        issues.append(
            f"No shared bands between the scenes ({sorted(a.bands)} vs {sorted(b.bands)})."
        )

    if a.modality == b.modality:
        configuration = "bitemporal_pair"
        if a.acquisition_date and b.acquisition_date and a.acquisition_date == b.acquisition_date:
            warnings.append("Both scenes carry the same acquisition date - change analysis may be trivial.")
    elif {a.modality, b.modality} & {"sar"} and {a.modality, b.modality} & {"optical", "multispectral"}:
        configuration = "cross_modal_pair"
    else:
        configuration = "bitemporal_pair"
        warnings.append(f"Mixed modalities {a.modality}/{b.modality} treated as a temporal pair.")

    return {
        "compatible": not issues,
        "configuration": configuration,
        "same_grid": same_shape,
        "co_registered": bool(geo_ok or (not a.bbox and not b.bbox and same_shape)),
        "max_corner_offset_deg": round(offset, 8) if offset is not None else None,
        "shared_bands": shared,
        "modality_a": a.modality,
        "modality_b": b.modality,
        "date_a": a.acquisition_date,
        "date_b": b.acquisition_date,
        "issues": issues,
        "warnings": warnings,
    }


def check_single_scene(scene: Scene, task_needs: list[str] | None = None) -> dict:
    """Validate one scene against what the requested task needs."""
    needs = task_needs or []
    missing = [b for b in needs if b not in scene.bands]
    issues: list[str] = []
    warnings: list[str] = []
    if missing:
        issues.append(
            f"Requested analysis needs band(s) {missing}, but this scene provides "
            f"{sorted(scene.bands)}."
        )
    if scene.valid_mask.mean() < 0.05:
        issues.append("Fewer than 5% of pixels are valid - the scene is effectively empty.")
    elif scene.valid_mask.mean() < 0.6:
        warnings.append(
            f"Only {scene.valid_mask.mean() * 100:.0f}% of pixels are valid; "
            "statistics are computed over the valid subset only."
        )
    if not scene.georeferenced:
        warnings.append("Scene is not georeferenced - areas are reported in pixels, not km².")
    return {
        "compatible": not issues,
        "modality": scene.modality,
        "bands": sorted(scene.bands),
        "missing_bands": missing,
        "valid_fraction": round(float(scene.valid_mask.mean()), 4),
        "georeferenced": scene.georeferenced,
        "issues": issues,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
#: Leading bytes that identify each accepted container.
#:
#: An extension is a claim, not evidence. Checking the first bytes turns the
#: two commonest upload failures - a PDF or a ZIP renamed to .tif, and a
#: download that stopped partway - into one clear sentence at the door, rather
#: than a decoder traceback several layers down.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"II*\x00", "TIFF"), (b"MM\x00*", "TIFF"),            # little / big endian
    (b"II+\x00", "BigTIFF"), (b"MM\x00+", "BigTIFF"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"BM", "BMP"),
    (b"RIFF", "WebP"),
)


def sniff_format(data: bytes) -> str | None:
    """Identify the container from its leading bytes, or None if unknown."""
    for sig, name in _MAGIC:
        if data.startswith(sig):
            if name == "WebP" and data[8:12] != b"WEBP":
                continue
            return name
    return None


def save_upload(data: bytes, filename: str) -> Path:
    name = Path(filename).name or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ImageLoadError(
            f"'{name}' has an unsupported extension ({ext or 'none'}). Accepted: "
            ".tif/.tiff/.geotiff for geospatial imagery, or .png/.jpg/.jpeg/.bmp/"
            ".webp for ordinary images."
        )
    if not data:
        raise ImageLoadError(f"'{name}' is empty (0 bytes). The upload did not complete.")
    if len(data) < 32:
        raise ImageLoadError(
            f"'{name}' is only {len(data)} bytes, which is too small to be an image. "
            "The file is most likely truncated.")
    mb = len(data) / (1024 * 1024)
    if mb > settings.max_upload_mb:
        raise ImageLoadError(
            f"'{name}' is {mb:.1f} MB; the upload limit is "
            f"{settings.max_upload_mb} MB. Crop or compress it first.")

    detected = sniff_format(data)
    if detected is None:
        raise ImageLoadError(
            f"'{name}' does not look like an image file. Its contents do not match "
            "TIFF, PNG, JPEG, BMP or WebP - check that you selected the right file "
            "and that it downloaded completely.")
    if ext in GEO_EXT and not detected.endswith("TIFF"):
        raise ImageLoadError(
            f"'{name}' is named as a TIFF but its contents are {detected}. Rename it "
            f"to .{detected.lower()} and upload it as an ordinary image, or supply the "
            "actual GeoTIFF.")
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    # The scene id is the filename prefix, and the loader recovers it with
    # glob("<id>*"), so the rest of the name must not contain path separators
    # or glob metacharacters.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80] or "upload"
    dest = settings.uploads_dir / f"{uuid.uuid4().hex[:10]}_{safe}"
    dest.write_bytes(data)
    return dest


def write_sidecar(path: Path, info: dict) -> None:
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(info, indent=2, default=str), encoding="utf-8"
    )
