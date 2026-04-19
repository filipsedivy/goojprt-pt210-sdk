"""Tests for GoojPrtPT210 facade — covers the uncovered methods."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt.printer import GoojPrtPT210
from goojprt.transport.ble import BleTransport
from goojprt.transport.spp import SppTransport
from goojprt.enums import Align, CodePage


# ── helpers ───────────────────────────────────────────────────────────────────

def _ble_printer() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.is_connected = True
    p._ble.write = AsyncMock()
    p._ble.write_raster_strip = AsyncMock()
    return p


def _spp_printer() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._spp = MagicMock(spec=SppTransport)
    p._spp.is_connected = True
    return p


# ── BLE lifecycle ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_ble_creates_transport_and_calls_scan():
    p = GoojPrtPT210()
    mock_ble = MagicMock(spec=BleTransport)
    mock_ble.scan = AsyncMock(return_value=[{"name": "P", "address": "X"}])
    with patch("goojprt.printer.BleTransport", return_value=mock_ble):
        result = await p.scan_ble(timeout=1.0)
    assert result == [{"name": "P", "address": "X"}]


@pytest.mark.asyncio
async def test_scan_ble_reuses_existing_transport():
    p = GoojPrtPT210()
    existing = MagicMock(spec=BleTransport)
    existing.scan = AsyncMock(return_value=[])
    p._ble = existing
    await p.scan_ble()
    existing.scan.assert_called_once()


@pytest.mark.asyncio
async def test_connect_ble_creates_transport():
    mock_ble = MagicMock(spec=BleTransport)
    mock_ble.connect = AsyncMock()
    p = GoojPrtPT210()
    with patch("goojprt.printer.BleTransport", return_value=mock_ble):
        await p.connect_ble("AA:BB")
    mock_ble.connect.assert_called_once_with("AA:BB")


@pytest.mark.asyncio
async def test_connect_ble_reuses_existing_transport():
    p = GoojPrtPT210()
    existing = MagicMock(spec=BleTransport)
    existing.connect = AsyncMock()
    p._ble = existing
    await p.connect_ble("AA:BB")
    existing.connect.assert_called_once_with("AA:BB")


@pytest.mark.asyncio
async def test_disconnect_calls_ble_disconnect():
    p = GoojPrtPT210()
    mock_ble = MagicMock(spec=BleTransport)
    mock_ble.disconnect = AsyncMock()
    p._ble = mock_ble
    await p.disconnect()
    mock_ble.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_noop_when_no_transport():
    p = GoojPrtPT210()
    await p.disconnect()  # should not raise


def test_is_connected_ble_false_when_no_transport():
    assert GoojPrtPT210().is_connected_ble is False


def test_is_connected_ble_true_when_connected():
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.is_connected = True
    assert p.is_connected_ble is True


# ── SPP lifecycle ─────────────────────────────────────────────────────────────

def test_connect_spp_creates_transport():
    mock_spp = MagicMock(spec=SppTransport)
    p = GoojPrtPT210()
    with patch("goojprt.printer.SppTransport", return_value=mock_spp):
        p.connect_spp("AA:BB", port=2)
    mock_spp.connect.assert_called_once_with("AA:BB", 2)


def test_connect_spp_reuses_existing():
    p = GoojPrtPT210()
    existing = MagicMock(spec=SppTransport)
    p._spp = existing
    p.connect_spp("AA:BB")
    existing.connect.assert_called_once()


def test_disconnect_spp_calls_transport():
    p = _spp_printer()
    p.disconnect_spp()
    p._spp.disconnect.assert_called_once()


def test_disconnect_spp_noop_when_no_transport():
    GoojPrtPT210().disconnect_spp()


def test_is_connected_spp_false_when_none():
    assert GoojPrtPT210().is_connected_spp is False


def test_is_connected_spp_true_when_connected():
    p = _spp_printer()
    assert p.is_connected_spp is True


# ── BLE high-level API ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize_writes_init_bytes():
    p = _ble_printer()
    await p.initialize()
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_print_text_writes_bytes():
    p = _ble_printer()
    await p.print_text("hello")
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_print_line_writes_bytes():
    p = _ble_printer()
    await p.print_line()
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_feed_writes_bytes():
    p = _ble_printer()
    await p.feed(3)
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_cut_writes_bytes():
    p = _ble_printer()
    await p.cut()
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_print_qr_writes_bytes():
    p = _ble_printer()
    await p.print_qr("https://example.com")
    p._ble.write.assert_called_once()


@pytest.mark.asyncio
async def test_print_image_from_file(tmp_path):
    img_path = tmp_path / "test.png"
    Image.new("1", (384, 24), 1).save(str(img_path))
    p = _ble_printer()
    await p.print_image_from_file(str(img_path))
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_print_text_image_writes_raster():
    p = _ble_printer()
    await p.print_text_image("Hello")
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_print_grid_writes_raster():
    p = _ble_printer()
    cols = [{"width": 50, "align": "left", "text": "A"},
            {"width": 50, "align": "right", "text": "B"}]
    await p.print_grid(cols)
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_print_pdf417_writes_raster():
    p = _ble_printer()
    stub_img = Image.new("1", (384, 24), 1)
    with patch("goojprt.printer.rendering.render_pdf417", return_value=stub_img):
        await p.print_pdf417("test-data")
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_print_ekg_writes_raster():
    p = _ble_printer()
    await p.print_ekg()
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_set_charset_writes_bytes():
    p = _ble_printer()
    await p.set_charset(CodePage.WPC1250)
    p._ble.write.assert_called_once()


# ── query_printer_info ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_printer_info_no_notify_returns_error():
    p = _ble_printer()
    p._ble.has_notify = False
    result = await p.query_printer_info()
    assert "error" in result


@pytest.mark.asyncio
async def test_query_printer_info_with_notify_returns_dict():
    p = _ble_printer()
    p._ble.has_notify = True
    p._ble.clear_notify_buffer = MagicMock()
    p._ble.read_notify = AsyncMock(return_value=b"PT210\x00")
    result = await p.query_printer_info(timeout=0.1)
    assert "model_id" in result
    assert "raw_responses" in result


# ── query_full_info ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_full_info_returns_expected_keys():
    p = _ble_printer()
    p._ble.has_notify = False
    p._ble.read_gatt = AsyncMock(side_effect=Exception("no gatt"))
    result = await p.query_full_info(timeout=0.1)
    assert "ble_device" in result
    assert "ble_battery" in result
    assert "escpos_status" in result
    assert "escpos_info" in result


@pytest.mark.asyncio
async def test_query_full_info_with_battery_and_notify():
    p = _ble_printer()
    p._ble.has_notify = True
    p._ble.clear_notify_buffer = MagicMock()
    p._ble.read_notify = AsyncMock(return_value=b"\x00")

    async def mock_read_gatt(uuid):
        if "2a19" in uuid:
            return b"\x64"  # battery 100%
        if "2a23" in uuid:
            return b"\x01\x02\x03\x04\x05\x06\x07\x08"
        return b"MockValue\x00"

    p._ble.read_gatt = mock_read_gatt
    result = await p.query_full_info(timeout=0.1)
    assert result["ble_battery"].get("level_pct") == 100


# ── probe_charsets ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_charsets_runs_without_error():
    p = _ble_printer()
    p._ble.has_notify = False
    await p.probe_charsets(test_string="abc")
    assert p._ble.write.called


@pytest.mark.asyncio
async def test_probe_charsets_custom_pages():
    p = _ble_printer()
    p._ble.has_notify = False
    await p.probe_charsets(test_string="abc", pages=[CodePage.PC437])
    assert p._ble.write.called


# ── SPP high-level API ────────────────────────────────────────────────────────

def test_initialize_spp():
    p = _spp_printer()
    p.initialize_spp()
    p._spp.write.assert_called_once()


def test_print_text_spp():
    p = _spp_printer()
    p.print_text_spp("hello")
    p._spp.write.assert_called_once()


def test_feed_spp():
    p = _spp_printer()
    p.feed_spp(2)
    p._spp.write.assert_called_once()


def test_cut_spp():
    p = _spp_printer()
    p.cut_spp()
    p._spp.write.assert_called_once()


def test_print_qr_spp():
    p = _spp_printer()
    p.print_qr_spp("https://example.com")
    p._spp.write.assert_called_once()


def test_print_image_spp():
    p = _spp_printer()
    img = Image.new("1", (384, 24), 1)
    p.print_image_spp(img)
    assert p._spp.write_raster_strip.called


def test_print_pdf417_spp():
    p = _spp_printer()
    stub_img = Image.new("1", (384, 24), 1)
    with patch("goojprt.printer.rendering.render_pdf417", return_value=stub_img):
        p.print_pdf417_spp("test-data")
    assert p._spp.write_raster_strip.called
