"""Tests that GoojPrtPT210.print_image uses strip-based raster sending."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from PIL import Image

from goojprt.printer import GoojPrtPT210
from goojprt.transport.ble import BleTransport


def _make_printer_ble() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.is_connected = True
    p._ble.write_raster_strip = AsyncMock()
    return p


@pytest.mark.asyncio
async def test_print_image_calls_write_raster_strip_multiple_times():
    p = _make_printer_ble()
    img = Image.new("1", (384, 72), 1)  # 72 rows → 3 strips of 24
    await p.print_image(img, strip_height=24)
    assert p._ble.write_raster_strip.call_count == 3


@pytest.mark.asyncio
async def test_print_image_default_strip_height_is_24():
    p = _make_printer_ble()
    img = Image.new("1", (384, 48), 1)  # 48 rows → 2 strips of 24 (default)
    await p.print_image(img)
    assert p._ble.write_raster_strip.call_count == 2


@pytest.mark.asyncio
async def test_print_image_single_strip_for_small_image():
    p = _make_printer_ble()
    img = Image.new("1", (384, 10), 1)  # 10 rows → 1 strip
    await p.print_image(img, strip_height=24)
    assert p._ble.write_raster_strip.call_count == 1


@pytest.mark.asyncio
async def test_print_image_each_call_is_gsv0_payload():
    p = _make_printer_ble()
    img = Image.new("1", (384, 24), 1)
    await p.print_image(img, strip_height=24)
    strip_bytes = p._ble.write_raster_strip.call_args[0][0]
    assert strip_bytes[:2] == bytes([0x1D, 0x76])


@pytest.mark.asyncio
async def test_print_image_passes_rows_to_write_raster_strip():
    """Verify rows are extracted from GS v 0 header and passed to transport."""
    p = _make_printer_ble()
    img = Image.new("1", (384, 72), 1)  # 72 rows → 3 strips of 24
    await p.print_image(img, strip_height=24)

    # Verify each call passes rows=24
    calls = p._ble.write_raster_strip.call_args_list
    assert len(calls) == 3
    for call in calls:
        # call[1] is kwargs, should have rows=24
        assert call[1] == {"rows": 24}


@pytest.mark.asyncio
async def test_print_image_rows_for_last_strip_partial():
    """Verify rows are correct for partial last strip."""
    p = _make_printer_ble()
    img = Image.new("1", (384, 50), 1)  # 50 rows → 3 strips (24 + 24 + 2)
    await p.print_image(img, strip_height=24)

    calls = p._ble.write_raster_strip.call_args_list
    assert len(calls) == 3
    # First two strips: rows=24
    assert calls[0][1] == {"rows": 24}
    assert calls[1][1] == {"rows": 24}
    # Last strip: rows=2
    assert calls[2][1] == {"rows": 2}
