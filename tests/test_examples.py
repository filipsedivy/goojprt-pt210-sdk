"""Tests for EKG and Grid models, routes, and dispatch."""
from goojprt_server.models import PrintEkgRequest, PrintGridRequest


def test_ekg_model_defaults():
    m = PrintEkgRequest()
    assert m.beats == 4
    assert m.height_px == 160
    assert m.line_width == 2
    assert m.grid is True
    assert m.amplitude == 0.82
    assert m.portrait is False
    assert m.px_per_beat == 240


def test_ekg_model_validation():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrintEkgRequest(beats=0)
    with pytest.raises(ValidationError):
        PrintEkgRequest(amplitude=1.5)


def test_grid_model_defaults():
    m = PrintGridRequest(columns=[{"width": 50, "align": "left", "text": "A"}])
    assert m.font_size == 22
    assert m.dither is False


def test_grid_model_requires_columns():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrintGridRequest()
