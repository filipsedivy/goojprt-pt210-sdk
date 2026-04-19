"""Tests for print_template — covers all item types and edge cases."""
import asyncio
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import os

import pytest

from goojprt.template import print_template


def _make_toml(items_toml: str) -> str:
    """Write a temporary TOML file and return its path."""
    content = f"items = [\n{items_toml}\n]\n"
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


def _mock_printer():
    p = MagicMock()
    p.connect_ble = AsyncMock()
    p.initialize = AsyncMock()
    p.disconnect = AsyncMock()
    p.print_text_image = AsyncMock()
    p.print_text = AsyncMock()
    p.print_pdf417 = AsyncMock()
    p.print_qr = AsyncMock()
    p.print_line = AsyncMock()
    p.feed = AsyncMock()
    p.cut = AsyncMock()
    p.print_grid = AsyncMock()
    p.print_ekg = AsyncMock()
    return p


@pytest.mark.asyncio
async def test_print_template_empty_items(capsys):
    path = _make_toml("")
    try:
        await print_template("AA:BB", path)
        out = capsys.readouterr().out
        assert "no items" in out
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_text_image(capsys):
    path = _make_toml('{ type = "text_image", text = "Hello" },')
    printer = _mock_printer()
    try:
        with patch("goojprt.template.GoojPrtPT210", return_value=printer):
            await print_template("AA:BB", path)
        printer.print_text_image.assert_called_once()
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_text(capsys):
    path = _make_toml('{ type = "text", text = "Hi" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_text.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_pdf417():
    path = _make_toml('{ type = "pdf417", data = "ABC" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_pdf417.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_qr():
    path = _make_toml('{ type = "qr", data = "https://x.com" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_qr.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_line():
    path = _make_toml('{ type = "line" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_line.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_feed():
    path = _make_toml('{ type = "feed", lines = 2 },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.feed.assert_called_once_with(2)
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_cut():
    path = _make_toml('{ type = "cut" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.cut.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_grid():
    path = _make_toml(
        '{ type = "grid", columns = [{width=50, align="left", text="A"}, '
        '{width=50, align="right", text="B"}] },'
    )
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_grid.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_ekg():
    path = _make_toml('{ type = "ekg", beats = 2 },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    printer.print_ekg.assert_called_once()
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_unknown_type_skipped(capsys):
    path = _make_toml('{ type = "unicorn" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path)
    out = capsys.readouterr().out
    assert "Unknown item type" in out
    os.unlink(path)


@pytest.mark.asyncio
async def test_print_template_variable_substitution():
    path = _make_toml('{ type = "text", text = "{{custom}}" },')
    printer = _mock_printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", path, extra_vars={"custom": "injected"})
    call_kwargs = printer.print_text.call_args
    assert call_kwargs[0][0] == "injected"
    os.unlink(path)
