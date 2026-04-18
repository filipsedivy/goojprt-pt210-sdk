"""Bluetooth Low Energy transport backed by :mod:`bleak`.

Handles three concerns that any BLE-facing printer driver must address:

1. **Characteristic discovery.** The write characteristic is located by
   UUID (primary then alternate GoojPrt family UUIDs); the optional
   notify characteristic is registered if present, so the printer's
   responses can be read back.
2. **MTU chunking with pacing.** BLE packets are limited by the
   connection MTU; ``write-without-response`` is used (no ACK from the
   link layer) so a small sleep between chunks is required to avoid
   overflowing the peripheral's queue.
3. **Post-raster throttle.** After a large raster image, the peripheral
   needs time to actually feed paper. A short sleep proportional to the
   number of raster rows is inserted to keep the producer in sync with
   the paper motor.
"""

import asyncio
from typing import Optional

from goojprt.constants import (
    BLE_NOTIFY_CHAR_UUID,
    BLE_NOTIFY_CHAR_UUID_ALT,
    BLE_SERVICE_UUID,
    BLE_SERVICE_UUID_ALT,
    BLE_WRITE_CHAR_UUID,
    BLE_WRITE_CHAR_UUID_ALT,
)

try:
    from bleak import BleakClient, BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


class BleTransport:
    """Asynchronous BLE transport for GoojPrt PT-210 printers.

    All methods are ``async``. Instances are not thread-safe — use a
    single transport from a single event loop at a time.
    """

    #: BLE MTU minus protocol overhead. Most GoojPrt firmware handles 182 bytes.
    CHUNK_SIZE = 182
    #: Pause between chunks, covers the typical BLE connection interval (~30 ms).
    CHUNK_DELAY = 0.04

    def __init__(self, on_disconnect=None) -> None:
        """Create a disconnected transport; call :meth:`connect` to attach."""
        self._client: Optional["BleakClient"] = None
        self._write_char: Optional[str] = None
        self._notify_char: Optional[str] = None
        self._notify_buffer: bytearray = bytearray()
        self._on_disconnect_cb = on_disconnect

    async def scan(self, timeout: float = 10.0) -> list[dict]:
        """Discover nearby BLE devices.

        :param timeout: Scan duration in seconds.
        :returns: List of ``{"name": str, "address": str}`` dictionaries.
        :raises ImportError: When :mod:`bleak` is not installed.
        """
        if not BLEAK_AVAILABLE:
            raise ImportError("bleak is required: pip install bleak")
        devices = await BleakScanner.discover(timeout=timeout)
        return [{"name": d.name or "?", "address": d.address} for d in devices]

    async def connect(self, address: str) -> None:
        """Connect to the printer and locate the write/notify characteristics.

        :param address: Bluetooth MAC address (or UUID on macOS).
        :raises ImportError: When :mod:`bleak` is not installed.
        :raises RuntimeError: When no write characteristic can be found
            (the device is probably not a GoojPrt PT-210).
        """
        if not BLEAK_AVAILABLE:
            raise ImportError("bleak is required: pip install bleak")

        self._client = BleakClient(address, disconnected_callback=self._on_disconnect_cb)
        await self._client.connect()
        self._write_char = await self._find_write_characteristic()
        if not self._write_char:
            await self._client.disconnect()
            raise RuntimeError(
                "Failed to locate the write characteristic. "
                "The remote device is probably not a GoojPrt PT-210."
            )

    async def _find_write_characteristic(self) -> Optional[str]:
        """Walk the GATT services and resolve write + notify characteristics.

        Tries the primary UUIDs first, then the alternates. If a notify
        characteristic is found, subscribes to it so that :meth:`_on_notify`
        captures any incoming responses.

        :returns: UUID of the write characteristic, or ``None`` when none
            is found.
        """
        write_char = None
        for service in self._client.services:
            for char in service.characteristics:
                if "notify" in char.properties and self._notify_char is None:
                    if char.uuid.lower() in (
                        BLE_NOTIFY_CHAR_UUID.lower(),
                        BLE_NOTIFY_CHAR_UUID_ALT.lower(),
                    ):
                        self._notify_char = char.uuid

                if char.uuid.lower() in (
                    BLE_WRITE_CHAR_UUID.lower(),
                    BLE_WRITE_CHAR_UUID_ALT.lower(),
                ):
                    write_char = char.uuid
                    continue
                if write_char is None:
                    if "write-without-response" in char.properties or "write" in char.properties:
                        if service.uuid.lower() in (
                            BLE_SERVICE_UUID.lower(),
                            BLE_SERVICE_UUID_ALT.lower(),
                        ):
                            write_char = char.uuid

        if self._notify_char:
            await self._client.start_notify(self._notify_char, self._on_notify)

        return write_char

    def _on_notify(self, _sender, data: bytearray) -> None:
        """Callback for inbound notifications (e.g. responses to ``GS I``)."""
        self._notify_buffer.extend(data)

    async def disconnect(self) -> None:
        """Disconnect from the printer and release all references."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._write_char = None

    @property
    def is_connected(self) -> bool:
        """Whether the BLE client is currently connected."""
        return bool(self._client and self._client.is_connected)

    @property
    def has_notify(self) -> bool:
        """Whether the remote device exposes a notify characteristic."""
        return self._notify_char is not None

    async def write(self, data: bytes) -> None:
        """Send raw bytes over BLE with MTU chunking and pacing.

        :param data: Bytes to send.
        :raises RuntimeError: When the transport is not connected.
        """
        if not self.is_connected:
            raise RuntimeError("BLE transport is not connected.")
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i : i + self.CHUNK_SIZE]
            await self._client.write_gatt_char(
                self._write_char, chunk, response=False
            )
            await asyncio.sleep(self.CHUNK_DELAY)

    async def write_image_data(self, data: bytes, rows: int) -> None:
        """Send raster data followed by a throttle proportional to image height.

        After the final chunk, sleeps ``max(0.3, rows * 0.002)`` seconds
        so the printer's internal queue can drain before the next command
        is issued (``write-without-response`` does not provide flow
        control on its own).
        """
        await self.write(data)
        await asyncio.sleep(max(0.3, rows * 0.002))

    async def read_notify(self, timeout: float) -> bytes:
        """Return the current notify buffer after waiting ``timeout`` seconds.

        Callers typically call :meth:`clear_notify_buffer` beforehand to
        discard responses from earlier queries.
        """
        await asyncio.sleep(timeout)
        return bytes(self._notify_buffer)

    def clear_notify_buffer(self) -> None:
        """Drop any buffered notify bytes (call before issuing a new query)."""
        self._notify_buffer.clear()

    async def read_gatt(self, uuid: str) -> bytes:
        """Read a raw value from a GATT characteristic (e.g. Device Info).

        :raises RuntimeError: When the transport is not connected.
        """
        if not self.is_connected:
            raise RuntimeError("BLE transport is not connected.")
        return await self._client.read_gatt_char(uuid)
