"""Tests for goojprt.raster — image_to_raster and pad_image_to_paper_width."""

import pytest
from PIL import Image
from goojprt.raster import image_to_raster, pad_image_to_paper_width
from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align

GS_V_0_HEADER = bytes([0x1D, 0x76, 0x30, 0x00])
WIDTH_BYTES = PAPER_WIDTH_PX // 8  # 48


def make_image(width=PAPER_WIDTH_PX, height=10, mode="1"):
    return Image.new(mode, (width, height), 1)


class TestImageToRaster:
    def test_starts_with_gs_v_0(self):
        result = image_to_raster(make_image())
        assert result[:4] == GS_V_0_HEADER

    def test_header_encodes_width_bytes(self):
        result = image_to_raster(make_image())
        assert result[4] == WIDTH_BYTES & 0xFF
        assert result[5] == (WIDTH_BYTES >> 8) & 0xFF

    def test_header_encodes_height(self):
        img = make_image(height=20)
        result = image_to_raster(img)
        assert result[6] == 20
        assert result[7] == 0

    def test_payload_length(self):
        height = 10
        img = make_image(height=height)
        result = image_to_raster(img)
        expected_pixel_bytes = WIDTH_BYTES * height
        assert len(result) == 8 + expected_pixel_bytes

    def test_accepts_rgb_image(self):
        img = make_image(mode="RGB")
        result = image_to_raster(img)
        assert result[:4] == GS_V_0_HEADER

    def test_wider_image_cropped(self):
        img = make_image(width=PAPER_WIDTH_PX + 50, height=5)
        result = image_to_raster(img)
        assert result[4] == WIDTH_BYTES & 0xFF

    def test_narrower_image_padded(self):
        img = make_image(width=100, height=5)
        result = image_to_raster(img)
        assert result[4] == WIDTH_BYTES & 0xFF

    def test_all_white_image_has_zero_bits(self):
        img = Image.new("1", (PAPER_WIDTH_PX, 8), 1)  # 1 = white in mode "1"
        result = image_to_raster(img)
        # All pixel bytes should be 0 (no black dots)
        assert all(b == 0 for b in result[8:])

    def test_all_black_image_has_set_bits(self):
        img = Image.new("1", (PAPER_WIDTH_PX, 8), 0)  # 0 = black
        result = image_to_raster(img)
        assert all(b == 0xFF for b in result[8:])


class TestPadImageToPaperWidth:
    def test_narrow_left_has_correct_width(self):
        img = make_image(width=100, height=10)
        result = pad_image_to_paper_width(img, Align.LEFT)
        assert result.width == PAPER_WIDTH_PX

    def test_narrow_center_has_correct_width(self):
        img = make_image(width=100, height=10)
        result = pad_image_to_paper_width(img, Align.CENTER)
        assert result.width == PAPER_WIDTH_PX

    def test_narrow_right_has_correct_width(self):
        img = make_image(width=100, height=10)
        result = pad_image_to_paper_width(img, Align.RIGHT)
        assert result.width == PAPER_WIDTH_PX

    def test_height_preserved(self):
        img = make_image(width=100, height=15)
        result = pad_image_to_paper_width(img, Align.LEFT)
        assert result.height == 15

    def test_full_width_image_returned_unchanged(self):
        img = make_image(width=PAPER_WIDTH_PX, height=5)
        result = pad_image_to_paper_width(img, Align.LEFT)
        assert result is img

    def test_wider_image_returned_unchanged(self):
        img = make_image(width=PAPER_WIDTH_PX + 10, height=5)
        result = pad_image_to_paper_width(img, Align.LEFT)
        assert result is img

class TestPackBits:
    """``_pack_bits`` turns PIL polarity (1 = white) into ESC/POS polarity (1 = black)."""

    def test_leftmost_pixel_is_the_most_significant_bit(self):
        from goojprt.raster import _pack_bits

        img = Image.new("1", (16, 1), 1)
        img.putpixel((0, 0), 0)    # black, leftmost
        img.putpixel((15, 0), 0)   # black, rightmost
        assert _pack_bits(img) == bytes([0b10000000, 0b00000001])

    def test_all_black_and_all_white(self):
        from goojprt.raster import _pack_bits

        assert _pack_bits(Image.new("1", (8, 2), 0)) == b"\xff\xff"
        assert _pack_bits(Image.new("1", (8, 2), 1)) == b"\x00\x00"

    def test_width_not_multiple_of_eight_is_padded_with_white(self):
        from goojprt.raster import _pack_bits

        img = Image.new("1", (10, 1), 0)  # ten black pixels
        assert _pack_bits(img) == bytes([0xFF, 0b11000000])  # padding bits stay white

    def test_rows_stay_in_order(self):
        from goojprt.raster import _pack_bits

        img = Image.new("1", (8, 2), 1)
        img.putpixel((0, 1), 0)
        assert _pack_bits(img) == bytes([0x00, 0x80])

    def test_does_not_need_numpy(self, monkeypatch):
        import sys
        from goojprt.raster import image_to_raster

        monkeypatch.setitem(sys.modules, "numpy", None)  # import numpy -> ImportError
        assert image_to_raster(Image.new("L", (384, 4), 0))[:4] == GS_V_0_HEADER
