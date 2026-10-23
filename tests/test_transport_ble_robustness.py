"""Tests for BleTransport write atomicity, MTU limits, tunables and cleanup."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt.constants import BLE_NOTIFY_CHAR_UUID, BLE_WRITE_CHAR_UUID
from goojprt.transport.ble import BleTransport


def _connected() -> BleTransport:
    t = BleTransport()
    t._client = MagicMock()
    t._client.is_connected = True
    t._write_char = "w-uuid"
    return t


def _gatt_client(*chars, start_notify=None, services_uuid="0000ae30-0000-1000-8000-00805f9b34fb"):
    service = MagicMock()
    service.uuid = services_uuid
    service.characteristics = list(chars)
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.start_notify = start_notify or AsyncMock()
    client.services = [service]
    return client


def _write_char(max_size):
    char = MagicMock()
    char.uuid = BLE_WRITE_CHAR_UUID
    char.properties = ["write-without-response"]
    char.max_write_without_response_size = max_size
    return char


def _notify_char():
    char = MagicMock()
    char.uuid = BLE_NOTIFY_CHAR_UUID
    char.properties = ["notify"]
    return char


async def _connect(transport: BleTransport, client) -> None:
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=client):
        await transport.connect("AA:BB:CC:DD:EE:FF")


# ── atomic writes ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_writes_do_not_interleave_chunks():
    t = _connected()
    t.CHUNK_DELAY = 0
    order: list[int] = []

    async def write_gatt_char(_char, chunk, response):
        order.append(chunk[0])
        await asyncio.sleep(0)  # yield, so an unlocked writer would interleave

    t._client.write_gatt_char = write_gatt_char
    a = bytes([1]) * (t.chunk_size * 3)
    b = bytes([2]) * (t.chunk_size * 3)
    await asyncio.gather(t.write(a), t.write(b))

    assert order in ([1, 1, 1, 2, 2, 2], [2, 2, 2, 1, 1, 1])


@pytest.mark.asyncio
async def test_raster_strip_and_write_do_not_interleave():
    t = _connected()
    t.CHUNK_DELAY = 0
    order: list[int] = []

    async def write_gatt_char(_char, chunk, response):
        order.append(chunk[0])
        await asyncio.sleep(0)

    t._client.write_gatt_char = write_gatt_char
    strip = bytes([7]) * (t.chunk_size_raster * 3)
    query = bytes([9]) * (t.chunk_size * 2)
    await asyncio.gather(t.write_raster_strip(strip, rows=1), t.write(query))

    assert order in ([7, 7, 7, 9, 9], [9, 9, 7, 7, 7])


@pytest.mark.asyncio
async def test_failed_write_releases_the_lock():
    t = _connected()
    t.CHUNK_DELAY = 0
    t._client.write_gatt_char = AsyncMock(side_effect=[OSError("link lost"), None])

    with pytest.raises(OSError):
        await t.write(b"x")
    await asyncio.wait_for(t.write(b"y"), timeout=1.0)  # would hang if still locked


# ── negotiated payload limit ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_caps_chunks_to_negotiated_payload():
    t = BleTransport()
    await _connect(t, _gatt_client(_write_char(100)))

    assert t.chunk_size == 100
    assert t.chunk_size_raster == 100

    t._client.write_gatt_char = AsyncMock()
    with patch("asyncio.sleep", new=AsyncMock()):
        await t.write(bytes(250))
    assert [len(c.args[1]) for c in t._client.write_gatt_char.call_args_list] == [100, 100, 50]


@pytest.mark.asyncio
async def test_large_negotiated_payload_keeps_default_chunk_sizes():
    t = BleTransport()
    await _connect(t, _gatt_client(_write_char(244)))
    assert t.chunk_size == BleTransport.CHUNK_SIZE
    assert t.chunk_size_raster == BleTransport.CHUNK_SIZE_RASTER


@pytest.mark.asyncio
async def test_raster_chunk_is_capped_when_stack_reports_182():
    t = BleTransport()
    await _connect(t, _gatt_client(_write_char(182)))
    assert t.chunk_size == 182
    assert t.chunk_size_raster == 182  # default is 192, which exceeds the limit


@pytest.mark.parametrize("reported", [20, 0, None, MagicMock()])
@pytest.mark.asyncio
async def test_default_or_unknown_payload_limit_is_ignored(reported):
    # 20 is the stack default before the MTU exchange (BlueZ < 5.62 always says 20).
    t = BleTransport()
    await _connect(t, _gatt_client(_write_char(reported)))
    assert t._max_payload is None
    assert t.chunk_size == BleTransport.CHUNK_SIZE


# ── tunables ──────────────────────────────────────────────────────────────────

def test_chunk_overrides_apply_to_plain_and_raster_writes():
    t = BleTransport(chunk_size=50, chunk_delay=0.0)
    assert t.chunk_size == 50
    assert t.chunk_size_raster == 50
    assert t.chunk_delay == 0.0


def test_override_can_exceed_the_defaults_when_the_link_allows_it():
    t = BleTransport(chunk_size=240)
    assert t.chunk_size == 240
    assert t.chunk_size_raster == 240


@pytest.mark.asyncio
async def test_override_is_still_capped_by_the_negotiated_payload():
    t = BleTransport(chunk_size=240)
    await _connect(t, _gatt_client(_write_char(100)))
    assert t.chunk_size == 100
    assert t.chunk_size_raster == 100


def test_instance_assigned_class_constants_are_still_honoured():
    t = BleTransport()
    t.CHUNK_DELAY = 0.01
    assert t.chunk_delay == 0.01


@pytest.mark.asyncio
async def test_chunk_delay_override_is_used_between_chunks():
    t = _connected()
    t._chunk_delay_override = 0.0
    t._client.write_gatt_char = AsyncMock()
    sleeps: list[float] = []

    async def fake_sleep(duration):
        sleeps.append(duration)

    with patch("asyncio.sleep", new=fake_sleep):
        await t.write(bytes(t.chunk_size * 2))
    assert sleeps == [0.0, 0.0]


# ── notify buffer and state reset ────────────────────────────────────────────

def test_notify_buffer_keeps_only_the_newest_bytes():
    t = BleTransport()
    limit = BleTransport._NOTIFY_BUFFER_LIMIT
    t._on_notify(None, bytearray(b"\x01" * limit))
    t._on_notify(None, bytearray(b"\x02" * 10))
    assert len(t._notify_buffer) == limit
    assert bytes(t._notify_buffer[-10:]) == b"\x02" * 10
    assert t._notify_buffer[0] == 1


@pytest.mark.asyncio
async def test_disconnect_forgets_notify_state():
    t = _connected()
    t._notify_char = "n-uuid"
    t._notify_buffer.extend(b"stale")
    t._max_payload = 100
    t._client.disconnect = AsyncMock()

    await t.disconnect()

    assert t.has_notify is False
    assert not t._notify_buffer
    assert t._max_payload is None


@pytest.mark.asyncio
async def test_reconnect_does_not_keep_notify_char_from_previous_device():
    t = BleTransport()
    t._notify_char = "old-device-uuid"
    await _connect(t, _gatt_client(_write_char(None)))
    assert t.has_notify is False


# ── connect cleanup ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_disconnects_when_subscribing_to_notify_fails():
    client = _gatt_client(
        _notify_char(), _write_char(None),
        start_notify=AsyncMock(side_effect=OSError("cccd write failed")),
    )
    t = BleTransport()
    with pytest.raises(OSError, match="cccd"):
        await _connect(t, client)
    client.disconnect.assert_awaited_once()
