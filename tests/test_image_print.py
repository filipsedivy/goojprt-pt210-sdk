# tests/test_image_print.py
"""Unit tests for goojprt.rendering.image_print.prepare_image."""
import numpy as np
import pytest
from PIL import Image

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.rendering.image_print import prepare_image


def _rgb(w=100, h=100):
    return Image.new("RGB", (w, h), (128, 128, 128))


def test_output_is_1bit():
    result = prepare_image(_rgb())
    assert result.mode == "1"


def test_output_width_equals_paper_width():
    result = prepare_image(_rgb())
    assert result.width == PAPER_WIDTH_PX


def test_scale_half_still_padded_to_paper_width():
    result = prepare_image(_rgb(), scale=0.5)
    assert result.width == PAPER_WIDTH_PX


def test_rotate_90_swaps_dimensions_before_resize():
    result = prepare_image(_rgb(w=100, h=50), rotate=90)
    assert result.height > 50


def test_crop_reduces_content_area():
    full = prepare_image(_rgb(w=200, h=200))
    cropped = prepare_image(_rgb(w=200, h=200), crop=(0.0, 0.0, 0.5, 0.5))
    assert cropped.height < full.height


def test_dither_false_uses_threshold():
    white = Image.new("RGB", (50, 50), (255, 255, 255))
    result = prepare_image(white, dither=False, threshold=128)
    assert result.mode == "1"
    arr = np.asarray(result, dtype=np.uint8)
    assert arr.all()


def test_dither_true_ignores_threshold_param_and_still_returns_1bit():
    result = prepare_image(_rgb(), dither=True, threshold=0)
    assert result.mode == "1"


def test_align_center_pads_symmetrically():
    narrow = Image.new("RGB", (10, 10), (0, 0, 0))
    result = prepare_image(narrow, scale=0.025, align="center")
    assert result.width == PAPER_WIDTH_PX


def test_brightness_adjustment():
    result = prepare_image(_rgb(), brightness=1.5)
    assert result.mode == "1"


def test_contrast_adjustment():
    result = prepare_image(_rgb(), contrast=1.5)
    assert result.mode == "1"
