"""Tests for raster.image_to_raster_strips."""
from PIL import Image

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.raster import image_to_raster_strips


def _white(height: int) -> Image.Image:
    return Image.new("1", (PAPER_WIDTH_PX, height), 1)


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
    """Pixel data from all strips concatenated must equal image_to_raster output."""
    from goojprt.raster import image_to_raster

    # Top half black, bottom half white — non-trivial pattern
    img = Image.new("1", (PAPER_WIDTH_PX, 48), 1)
    for x in range(PAPER_WIDTH_PX):
        for y in range(24):
            img.putpixel((x, y), 0)  # black

    full = image_to_raster(img)
    full_pixels = full[8:]

    strips = image_to_raster_strips(img, strip_height=24)
    strip_pixels = b"".join(s[8:] for s in strips)

    assert strip_pixels == full_pixels
    # Verify the pattern is actually non-trivial
    assert full_pixels != bytes(len(full_pixels))  # not all zeros
