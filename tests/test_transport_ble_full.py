"""Tests for uncovered paths in goojprt.transport.ble.BleTransport."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from goojprt.transport.ble import BleTransport


def _connected(write_char="w-uuid", notify_char=None) -> BleTransport:
    t = BleTransport()
    t._client = MagicMock()
    t._client.is_connected = True
    t._write_char = write_char
    t._notify_char = notify_char
    return t


# ── scan ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_raises_import_error_when_bleak_unavailable():
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", False):
        t = BleTransport()
        with pytest.raises(ImportError, match="bleak"):
            await t.scan()


@pytest.mark.asyncio
async def test_scan_returns_name_address_dicts():
    dev = MagicMock()
    dev.name = "Printer"
    dev.address = "AA:BB:CC:DD:EE:FF"
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakScanner") as mock_scanner:
        mock_scanner.discover = AsyncMock(return_value=[dev])
        t = BleTransport()
        result = await t.scan(timeout=1.0)
    assert result == [{"name": "Printer", "address": "AA:BB:CC:DD:EE:FF"}]


@pytest.mark.asyncio
async def test_scan_device_without_name_uses_question_mark():
    dev = MagicMock()
    dev.name = None
    dev.address = "11:22:33:44:55:66"
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakScanner") as mock_scanner:
        mock_scanner.discover = AsyncMock(return_value=[dev])
        t = BleTransport()
        result = await t.scan()
    assert result[0]["name"] == "?"


# ── connect ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_raises_import_error_when_bleak_unavailable():
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", False):
        t = BleTransport()
        with pytest.raises(ImportError, match="bleak"):
            await t.connect("AA:BB:CC:DD:EE:FF")


@pytest.mark.asyncio
async def test_connect_raises_runtime_error_when_no_write_char():
    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.services = []

    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=mock_client):
        t = BleTransport()
        with pytest.raises(RuntimeError, match="write characteristic"):
            await t.connect("AA:BB:CC:DD:EE:FF")

    mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_connect_succeeds_with_matching_write_char():
    from goojprt.constants import BLE_WRITE_CHAR_UUID

    char = MagicMock()
    char.uuid = BLE_WRITE_CHAR_UUID
    char.properties = ["write-without-response"]

    service = MagicMock()
    service.uuid = "0000ae30-0000-1000-8000-00805f9b34fb"
    service.characteristics = [char]

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.services = [service]

    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=mock_client):
        t = BleTransport()
        await t.connect("AA:BB:CC:DD:EE:FF")

    assert t._write_char == BLE_WRITE_CHAR_UUID


# ── _find_write_characteristic: notify subscription ──────────────────────────

@pytest.mark.asyncio
async def test_find_write_characteristic_subscribes_notify():
    from goojprt.constants import BLE_WRITE_CHAR_UUID, BLE_NOTIFY_CHAR_UUID

    notify_char = MagicMock()
    notify_char.uuid = BLE_NOTIFY_CHAR_UUID
    notify_char.properties = ["notify"]

    write_char = MagicMock()
    write_char.uuid = BLE_WRITE_CHAR_UUID
    write_char.properties = ["write-without-response"]

    service = MagicMock()
    service.uuid = "0000ae30-0000-1000-8000-00805f9b34fb"
    service.characteristics = [notify_char, write_char]

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.start_notify = AsyncMock()
    mock_client.services = [service]

    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=mock_client):
        t = BleTransport()
        await t.connect("AA:BB:CC:DD:EE:FF")

    mock_client.start_notify.assert_called_once()
    assert t._notify_char == BLE_NOTIFY_CHAR_UUID


@pytest.mark.asyncio
async def test_find_write_characteristic_uses_alt_uuids():
    from goojprt.constants import BLE_WRITE_CHAR_UUID_ALT, BLE_NOTIFY_CHAR_UUID_ALT

    notify_char = MagicMock()
    notify_char.uuid = BLE_NOTIFY_CHAR_UUID_ALT
    notify_char.properties = ["notify"]

    write_char = MagicMock()
    write_char.uuid = BLE_WRITE_CHAR_UUID_ALT
    write_char.properties = ["write-without-response"]

    service = MagicMock()
    service.uuid = "unused"
    service.characteristics = [notify_char, write_char]

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.start_notify = AsyncMock()
    mock_client.services = [service]

    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=mock_client):
        t = BleTransport()
        await t.connect("AA:BB:CC:DD:EE:FF")

    assert t._write_char == BLE_WRITE_CHAR_UUID_ALT


@pytest.mark.asyncio
async def test_find_write_char_fallback_service_uuid():
    """Char without specific write UUID but in matching service + write property."""
    from goojprt.constants import BLE_SERVICE_UUID

    char = MagicMock()
    char.uuid = "0000ae01-0000-1000-8000-00805f9b34fb"
    char.properties = ["write-without-response"]

    service = MagicMock()
    service.uuid = BLE_SERVICE_UUID
    service.characteristics = [char]

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.services = [service]

    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=mock_client):
        t = BleTransport()
        await t.connect("AA:BB:CC:DD:EE:FF")

    assert t._write_char == char.uuid


# ── disconnect ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_when_not_connected_is_noop():
    t = BleTransport()
    await t.disconnect()  # should not raise


@pytest.mark.asyncio
async def test_disconnect_clears_refs():
    t = _connected()
    t._client.is_connected = True
    t._client.disconnect = AsyncMock()
    await t.disconnect()
    assert t._client is None
    assert t._write_char is None


# ── properties ────────────────────────────────────────────────────────────────

def test_is_connected_false_when_no_client():
    assert BleTransport().is_connected is False


def test_has_notify_false_by_default():
    assert BleTransport().has_notify is False


def test_has_notify_true_when_char_set():
    t = BleTransport()
    t._notify_char = "some-uuid"
    assert t.has_notify is True


# ── write ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_raises_when_not_connected():
    t = BleTransport()
    with pytest.raises(RuntimeError, match="not connected"):
        await t.write(b"hello")


@pytest.mark.asyncio
async def test_write_chunks_at_chunk_size():
    t = _connected()
    t._client.write_gatt_char = AsyncMock()
    data = bytes(BleTransport.CHUNK_SIZE * 3)
    with patch("asyncio.sleep", new=AsyncMock()):
        await t.write(data)
    assert t._client.write_gatt_char.call_count == 3


# ── notify helpers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_notify_returns_buffer():
    t = _connected(notify_char="n-uuid")
    t._notify_buffer = bytearray(b"\x01\x02\x03")
    with patch("asyncio.sleep", new=AsyncMock()):
        result = await t.read_notify(0.01)
    assert result == b"\x01\x02\x03"


def test_clear_notify_buffer_empties_it():
    t = BleTransport()
    t._notify_buffer = bytearray(b"\xff\xff")
    t.clear_notify_buffer()
    assert len(t._notify_buffer) == 0


def test_on_notify_appends_data():
    t = BleTransport()
    t._on_notify(None, bytearray(b"\xaa\xbb"))
    assert t._notify_buffer == bytearray(b"\xaa\xbb")


# ── read_gatt ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_gatt_raises_when_not_connected():
    t = BleTransport()
    with pytest.raises(RuntimeError, match="not connected"):
        await t.read_gatt("some-uuid")


@pytest.mark.asyncio
async def test_read_gatt_returns_bytes():
    t = _connected()
    t._client.read_gatt_char = AsyncMock(return_value=bytearray(b"\x42"))
    result = await t.read_gatt("some-uuid")
    assert result == b"\x42"
