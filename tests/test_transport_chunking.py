"""Tests for row-aligned chunking in BLE and SPP transports."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt.transport.ble import BleTransport


def _make_connected_transport() -> BleTransport:
    t = BleTransport()
    t._client = MagicMock()
    t._client.is_connected = True
    t._write_char = "fake-uuid"
    return t


@pytest.mark.asyncio
async def test_ble_chunk_size_raster_is_multiple_of_48():
    assert BleTransport.CHUNK_SIZE_RASTER % 48 == 0


@pytest.mark.asyncio
async def test_ble_write_raster_strip_chunks_at_192():
    t = _make_connected_transport()
    t._client.write_gatt_char = AsyncMock()

    # 384 bytes = exactly 2 chunks of 192
    data = bytes(384)
    with patch("asyncio.sleep", new=AsyncMock()):
        await t.write_raster_strip(data)

    calls = t._client.write_gatt_char.call_args_list
    assert len(calls) == 2
    assert len(calls[0].args[1]) == 192
    assert len(calls[1].args[1]) == 192


@pytest.mark.asyncio
async def test_ble_write_raster_strip_sends_all_bytes():
    t = _make_connected_transport()
    received = bytearray()

    async def capture(char, chunk, response):
        received.extend(chunk)

    t._client.write_gatt_char = capture
    data = bytes(range(256))
    with patch("asyncio.sleep", new=AsyncMock()):
        await t.write_raster_strip(data)

    assert bytes(received) == data


@pytest.mark.asyncio
async def test_ble_write_raster_strip_raises_when_disconnected():
    t = BleTransport()
    with pytest.raises(RuntimeError, match="not connected"):
        await t.write_raster_strip(b"\x00" * 48)


import time
from goojprt.transport.spp import SppTransport


def _make_connected_spp() -> SppTransport:
    t = SppTransport()
    t._sock = MagicMock()
    return t


def test_spp_chunk_size_raster_is_multiple_of_48():
    assert SppTransport.CHUNK_SIZE_RASTER % 48 == 0


def test_spp_write_raster_strip_chunks_at_192():
    t = _make_connected_spp()
    sent_chunks = []
    t._sock.send = lambda data: sent_chunks.append(bytes(data))

    data = bytes(384)
    with patch("time.sleep"):
        t.write_raster_strip(data)

    assert len(sent_chunks) == 2
    assert len(sent_chunks[0]) == 192
    assert len(sent_chunks[1]) == 192


def test_spp_write_raster_strip_sends_all_bytes():
    t = _make_connected_spp()
    received = bytearray()
    t._sock.send = lambda data: received.extend(data)

    data = bytes(range(200))
    with patch("time.sleep"):
        t.write_raster_strip(data)

    assert bytes(received) == data


def test_spp_write_raster_strip_raises_when_disconnected():
    t = SppTransport()
    with pytest.raises(RuntimeError, match="not connected"):
        t.write_raster_strip(b"\x00" * 48)
