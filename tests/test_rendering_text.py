"""Tests for goojprt.rendering.text.render_text_image."""

import pytest
from goojprt.rendering.text import render_text_image
from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align


class TestRenderTextImage:
    def test_returns_mode_1_image(self):
        img = render_text_image("Hello")
        assert img.mode == "1"

    def test_output_width_equals_paper_width(self):
        img = render_text_image("Hello")
        assert img.width == PAPER_WIDTH_PX

    def test_output_has_positive_height(self):
        img = render_text_image("Hello")
        assert img.height > 0

    def test_two_lines_taller_than_one(self):
        one = render_text_image("Line one")
        two = render_text_image("Line one\nLine two")
        assert two.height > one.height

    def test_dither_false_works(self):
        img = render_text_image("Test", dither=False, threshold=128)
        assert img.mode == "1"
        assert img.width == PAPER_WIDTH_PX

    def test_align_center(self):
        img = render_text_image("Center", align=Align.CENTER)
        assert img.width == PAPER_WIDTH_PX

    def test_align_right(self):
        img = render_text_image("Right", align=Align.RIGHT)
        assert img.width == PAPER_WIDTH_PX

    def test_empty_string_no_crash(self):
        img = render_text_image("")
        assert img.mode == "1"
        assert img.width == PAPER_WIDTH_PX

    def test_supersample_1_works(self):
        img = render_text_image("Hello", supersample=1)
        assert img.width == PAPER_WIDTH_PX

    def test_unicode_text(self):
        img = render_text_image("Héllo wörld")
        assert img.mode == "1"
        assert img.width == PAPER_WIDTH_PX

    def test_sharpen_enabled(self):
        img = render_text_image("Sharp", sharpen=True)
        assert img.mode == "1"
