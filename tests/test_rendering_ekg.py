"""Tests for goojprt.rendering.ekg.render_ekg."""

import pytest
from goojprt.rendering.ekg import render_ekg
from goojprt.constants import PAPER_WIDTH_PX


class TestRenderEkg:
    def test_returns_mode_1_image(self):
        img = render_ekg()
        assert img.mode == "1"

    def test_landscape_width_equals_paper_width(self):
        img = render_ekg(portrait=False)
        assert img.width == PAPER_WIDTH_PX

    def test_landscape_height_is_specified(self):
        img = render_ekg(height_px=80, portrait=False)
        assert img.height == 80

    def test_portrait_width_equals_paper_width(self):
        img = render_ekg(portrait=True)
        assert img.width == PAPER_WIDTH_PX

    def test_portrait_height_scales_with_beats(self):
        img2 = render_ekg(beats=2, portrait=True, px_per_beat=100)
        img4 = render_ekg(beats=4, portrait=True, px_per_beat=100)
        assert img4.height > img2.height

    def test_has_nonzero_pixels(self):
        from PIL import ImageChops
        img = render_ekg()
        # If all pixels were white, the image would have no dark pixels
        pixels = list(img.get_flattened_data())
        assert any(p == 0 for p in pixels), "Expected some black pixels (waveform)"

    def test_no_grid(self):
        img = render_ekg(grid=False)
        assert img.mode == "1"

    def test_multiple_beats(self):
        img = render_ekg(beats=6)
        assert img.mode == "1"
        assert img.width == PAPER_WIDTH_PX
