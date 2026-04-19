"""Tests for raster.image_to_raster_strips."""
import pytest
from PIL import Image

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.raster import image_to_raster_strips

PAPER_BYTES = PAPER_WIDTH_PX // 8  # 48


def _white(height: int) -> Image.Image:
    return Image.new("1", (PAPER_WIDTH_PX, height), 1)


def _gsv0_header(width_bytes: int, height: int) -> bytes:
    return bytes([
        0x1D, 0x76, 0x30, 0x00,
        width_bytes & 0xFF, (width_bytes >> 8) & 0xFF,
        height & 0xFF, (height >> 8) & 0xFF,
    ])


def test_single_strip_when_image_fits():
    img = _white(24)
    strips = image_to_raster_strips(img, strip_height=24)
    assert len(strips) == 1


def test_multiple_strips_for_tall_image():
    img = _white(100)
    strips = image_to_raster_strips(img, strip_height=24)
    # ceil(100 / 24) = 5
    assert len(strips) == 5


def test_each_strip_starts_with_gsv0():
    img = _white(48)
    strips = image_to_raster_strips(img, strip_height=24)
    for strip in strips:
        assert strip[:2] == bytes([0x1D, 0x76])


def test_strip_payload_length_matches_header():
    img = _white(48)
    strips = image_to_raster_strips(img, strip_height=24)
    for strip in strips:
        # Header declares width_bytes and height; payload must match.
        width_bytes = strip[4] | (strip[5] << 8)
        height = strip[6] | (strip[7] << 8)
        expected_payload = width_bytes * height
        assert len(strip) == 8 + expected_payload


def test_last_strip_covers_remainder():
    img = _white(30)
    strips = image_to_raster_strips(img, strip_height=24)
    # First strip: 24 rows, last strip: 6 rows
    last_height = strips[-1][6] | (strips[-1][7] << 8)
    assert last_height == 6


def test_all_strips_together_cover_full_image_height():
    height = 97
    img = _white(height)
    strips = image_to_raster_strips(img, strip_height=24)
    total_rows = sum(s[6] | (s[7] << 8) for s in strips)
    assert total_rows == height


def test_default_strip_height_is_24():
    img = _white(48)
    strips_default = image_to_raster_strips(img)
    strips_explicit = image_to_raster_strips(img, strip_height=24)
    assert strips_default == strips_explicit


def test_strips_pixel_data_matches_full_raster():
    """Concatenating all strip pixel data must equal a single image_to_raster payload."""
    from goojprt.raster import image_to_raster
    img = _white(48)
    full = image_to_raster(img)
    full_pixels = full[8:]  # skip GS v 0 header

    strips = image_to_raster_strips(img, strip_height=24)
    strip_pixels = b"".join(s[8:] for s in strips)

    assert strip_pixels == full_pixels
