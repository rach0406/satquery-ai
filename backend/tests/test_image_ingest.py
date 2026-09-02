"""Ingestion and analysis of ordinary images alongside GeoTIFFs.

The rule these tests protect: a missing map projection is a property of the
image, not a failure. Everything that does not need coordinates must still run,
and nothing may invent a coordinate for an image that has none.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.datasources import imagery_io as IO
from app.processing import indices as IX
from app.processing import regions as RG


@pytest.fixture
def scene_array() -> np.ndarray:
    """A small synthetic scene with water, vegetation and bright ground."""
    rng = np.random.default_rng(0)
    img = np.zeros((120, 180, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = 140, 120, 95        # bare soil
    img[10:45, 20:160] = [30, 90, 40]                            # vegetation
    img[60:90, 10:170] = [25, 60, 150]                           # water
    img[100:115, 30:90] = [195, 195, 200]                        # built-up
    return np.clip(img.astype(int) + rng.integers(-10, 10, img.shape), 0, 255).astype(np.uint8)


def _write(tmp_path, arr, name):
    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return p


# --------------------------------------------------------------------------
# Ordinary images load and are usable
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["a.png", "a.jpg", "a.tif", "a.bmp"])
def test_ordinary_images_load_in_pixel_space(tmp_path, scene_array, name):
    scene = IO.load_scene_file(_write(tmp_path, scene_array, name), scene_id="s")
    assert scene.spatial_reference == "pixel_space"
    assert scene.georeferenced is False
    assert set(scene.bands) == {"red", "green", "blue"}
    caps = scene.capabilities()
    # No coordinates, but the image is still fully analysable.
    assert caps["available"]["land_cover_segmentation"] is True
    assert caps["available"]["scene_classification"] is True
    assert caps["available"]["visual_question_answering"] is True
    assert "VARI" in caps["available"]["spectral_indices"]


def test_pixel_space_is_not_reported_as_an_error(tmp_path, scene_array):
    scene = IO.load_scene_file(_write(tmp_path, scene_array, "a.png"), scene_id="s")
    check = IO.check_single_scene(scene)
    assert check["compatible"] is True
    assert check["issues"] == []


def test_rgb_only_image_segments_via_visible_proxies(tmp_path, scene_array):
    scene = IO.load_scene_file(_write(tmp_path, scene_array, "a.png"), scene_id="s")
    seg = IX.segment_landcover(scene.bands, scene.valid_mask)
    assert seg.basis == "rgb"
    # The water strip is 30/120 rows over 160/180 cols ~ 22% of the frame.
    assert seg.fractions["water"] > 0.10
    assert seg.valid_pixels == scene.valid_mask.sum()
    assert any("no near-infrared" in n for n in seg.notes)


def test_multispectral_path_is_unchanged_when_nir_present():
    """The RGB fallback must not capture a scene that has real NIR."""
    h, w = 60, 60
    bands = {
        "red": np.full((h, w), 0.3, np.float32),
        "green": np.full((h, w), 0.3, np.float32),
        "blue": np.full((h, w), 0.3, np.float32),
        "nir": np.full((h, w), 0.7, np.float32),
    }
    bands["nir"][:20] = 0.05
    seg = IX.segment_landcover(bands, np.ones((h, w), bool))
    assert seg.basis == "multispectral"


def test_grayscale_stays_single_band(tmp_path, scene_array):
    gray = scene_array[..., 0]
    scene = IO.load_scene_file(_write(tmp_path, gray, "g.png"), scene_id="s")
    assert list(scene.bands) == ["gray"]
    assert scene.capabilities()["band_basis"] == "single_band"


# --------------------------------------------------------------------------
# Never invent geography
# --------------------------------------------------------------------------
def test_region_boxes_emit_no_coordinates_without_a_bbox():
    labels = np.zeros((40, 40), dtype=np.int32)
    labels[5:20, 5:25] = 1
    regs = RG.region_boxes(labels, 1, None, min_pixels=10)
    assert len(regs) == 1
    r = regs[0]
    assert r["georeferenced"] is False
    # The keys that would carry a fabricated position must be absent entirely.
    assert "bbox" not in r and "centroid" not in r and "area_km2" not in r
    assert r["pixel_bbox"] == [5, 5, 24, 19]
    assert "pixel" in RG.region_location(r)


def test_region_boxes_are_georeferenced_when_a_bbox_is_known():
    labels = np.zeros((40, 40), dtype=np.int32)
    labels[0:20, 0:20] = 1
    regs = RG.region_boxes(labels, 1, [80.0, 12.0, 81.0, 13.0], min_pixels=10)
    r = regs[0]
    assert r["georeferenced"] is True
    assert 80.0 <= r["centroid"][0] <= 81.0
    assert 12.0 <= r["centroid"][1] <= 13.0
    assert r["area_km2"] > 0


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------
def test_large_image_is_downscaled_not_refused(tmp_path):
    big = np.zeros((60, IO.MAX_ANALYSIS_SIDE + 800, 3), np.uint8)
    big[..., 1] = 120
    scene = IO.load_scene_file(_write(tmp_path, big, "big.png"), scene_id="s")
    assert max(scene.shape) <= IO.MAX_ANALYSIS_SIDE
    assert scene.metadata["original_size"][0] == IO.MAX_ANALYSIS_SIDE + 800


def test_corrupted_file_raises_a_readable_error(tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"junk" * 50)
    with pytest.raises(IO.ImageLoadError) as exc:
        IO.load_scene_file(p, scene_id="s")
    assert "corrupted" in str(exc.value).lower()


def test_unsupported_extension_names_what_is_accepted(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"hello")
    with pytest.raises(IO.ImageLoadError) as exc:
        IO.load_scene_file(p, scene_id="s")
    assert "not a supported image format" in str(exc.value)


def test_empty_upload_is_rejected_clearly():
    with pytest.raises(IO.ImageLoadError) as exc:
        IO.save_upload(b"", "empty.png")
    assert "empty" in str(exc.value).lower()
