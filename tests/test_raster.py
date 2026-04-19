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