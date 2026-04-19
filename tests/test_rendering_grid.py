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
