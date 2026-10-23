"""Tests for goojprt.rendering.grid.render_grid."""

import pytest
from goojprt.rendering.grid import render_grid
from goojprt.constants import PAPER_WIDTH_PX


def two_col():
    return [
        {"width": 50, "align": "left", "text": "Item"},
        {"width": 50, "align": "right", "text": "5 Kč"},
    ]


def three_col():
    return [
        {"width": 40, "align": "left", "text": "1 Kč"},
        {"width": 30, "align": "right", "text": "5 ks"},
        {"width": 30, "align": "right", "text": "5 Kč"},
    ]


class TestRenderGrid:
    def test_returns_mode_1_image(self):
        img = render_grid(two_col())
        assert img.mode == "1"

    def test_width_equals_paper_width(self):
        img = render_grid(two_col())
        assert img.width == PAPER_WIDTH_PX

    def test_three_columns(self):
        img = render_grid(three_col())
        assert img.width == PAPER_WIDTH_PX

    def test_positive_height(self):
        img = render_grid(two_col())
        assert img.height > 0

    def test_dither_true(self):
        img = render_grid(two_col(), dither=True)
        assert img.mode == "1"

    def test_empty_columns_list(self):
        img = render_grid([])
        assert img.width == PAPER_WIDTH_PX

    def test_single_column(self):
        img = render_grid([{"width": 100, "align": "center", "text": "Only"}])
        assert img.width == PAPER_WIDTH_PX

    def test_empty_text_column(self):
        cols = [
            {"width": 50, "align": "left", "text": ""},
            {"width": 50, "align": "right", "text": "Value"},
        ]
        img = render_grid(cols)
        assert img.mode == "1"

    def test_font_oserror_falls_back_to_default(self):
        from unittest.mock import patch
        with patch("goojprt.rendering.grid.find_system_font", return_value="/bad/font.ttf"):
            img = render_grid(two_col())
        assert img.mode == "1"
        assert img.width == PAPER_WIDTH_PX


class TestRowsLineUp:
    """Every row has the same height and baseline, whatever letters it holds."""

    @staticmethod
    def _row(text, align="left"):
        return render_grid([{"width": 100, "align": align, "text": text}])

    @staticmethod
    def _ink(img):
        from PIL import ImageChops
        return ImageChops.invert(img.convert("L")).getbbox()

    def test_accented_capitals_do_not_make_a_row_taller(self):
        heights = {self._row(t).height for t in ("Ubrousky", "Šampon", "Čaj černý", "gjpqy", "HHH", "ŽŘĚ")}
        assert len(heights) == 1

    def test_the_baseline_is_the_same_in_every_row(self):
        # No descenders in either word, so the ink bottom is the baseline.
        assert self._ink(self._row("HELLO"))[3] == self._ink(self._row("ŠĚLŘŽ"))[3]

    def test_accents_on_capitals_are_not_clipped(self):
        for text in ("ČŠŽĚŘ", "ÁÉÍÓÚÝ", "gjpqy"):
            img = self._row(text)
            left, top, right, bottom = self._ink(img)
            assert top > 0 and bottom < img.height

    def test_right_alignment_still_reaches_the_right_edge(self):
        left, top, right, bottom = self._ink(self._row("1 829,60", align="right"))
        assert 384 - right <= 10

    def test_a_table_of_rows_has_one_row_height(self):
        names = ["Ubrousky", "Šampon", "Uzená makrela", "Čaj černý", "Mléko 1 l"]
        assert len({render_grid([{"width": 70, "text": n}, {"width": 30, "align": "right", "text": "1"}]).height
                    for n in names}) == 1

    def test_the_legacy_bitmap_font_still_renders(self):
        from unittest.mock import patch
        from PIL import ImageFont

        if not hasattr(ImageFont, "load_default_imagefont"):
            pytest.skip("this Pillow has no bitmap fallback font")
        with patch("goojprt.rendering.grid.find_system_font", return_value="/bad/font.ttf"), \
             patch.object(ImageFont, "load_default", ImageFont.load_default_imagefont):
            # ASCII only: the legacy bitmap font cannot draw "č" (it never could)
            img = render_grid([{"width": 50, "text": "Item"}, {"width": 50, "align": "right", "text": "5 Kc"}])
        assert img.mode == "1" and img.width == PAPER_WIDTH_PX
