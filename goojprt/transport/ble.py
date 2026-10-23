"""Bluetooth Low Energy transport backed by :mod:`bleak`.

Handles four concerns that any BLE-facing printer driver must address:

1. **Characteristic discovery.** The write characteristic is located by
   UUID (primary then alternate GoojPrt family UUIDs); the optional
   notify characteristic is registered if present, so the printer's
   responses can be read back.
2. **MTU chunking with pacing.** BLE packets are limited by the
   connection MTU; ``write-without-response`` is used (no ACK from the
   link layer) so a small sleep between chunks is required to avoid
   overflowing the peripheral's queue. The printer sits behind a
   Microchip-style transparent UART module without flow control, so this
   pacing is open-loop: nothing tells the host when the printer is ready.
3. **Atomic writes.** A lock serialises :meth:`BleTransport.write` and
   :meth:`BleTransport.write_raster_strip`, so a status query issued from
   another task can never land between two chunks of a print job.
4. **Post-raster throttle.** After a large raster image, the peripheral
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
    single transport from a single event loop at a time. Several tasks on
    that loop may share it: writes are serialised internally.
    """

    #: BLE MTU minus protocol overhead. Most GoojPrt firmware handles 182 bytes.
    CHUNK_SIZE = 182
    #: Pause between chunks, covers the typical BLE connection interval (~30 ms).
    CHUNK_DELAY = 0.04
    #: Chunk size for raster data, counted from the start of the strip
    #: payload (the 8-byte ``GS v 0`` header included). The printer parses a
    #: byte stream, so chunk boundaries do not need to fall on raster rows.
    CHUNK_SIZE_RASTER = 192
    #: Largest write-without-response payload that is believed to be
    #: *negotiated* rather than the stack's default (20 bytes, or the value
    #: BlueZ < 5.62 always reports).
    _DEFAULT_MAX_PAYLOAD = 20
    #: Upper bound for the buffered notify bytes; older bytes are dropped.
    _NOTIFY_BUFFER_LIMIT = 4096

    def __init__(
        self,
        on_disconnect=None,
        *,
        chunk_size: Optional[int] = None,
        chunk_delay: Optional[float] = None,
    ) -> None:
        """Create a disconnected transport; call :meth:`connect` to attach.

        :param on_disconnect: Callback invoked by :mod:`bleak` when the link drops.
        :param chunk_size: Bytes per BLE write on this instance, for plain
            writes and raster strips alike (replaces :attr:`CHUNK_SIZE` and
            :attr:`CHUNK_SIZE_RASTER`). Still capped to the payload size the
            BLE stack reports after connecting.
        :param chunk_delay: Override for :attr:`CHUNK_DELAY` on this
            instance. Lower values print faster but risk dropped bytes.
        """
        self._client: Optional["BleakClient"] = None
        self._write_char: Optional[str] = None
        self._notify_char: Optional[str] = None
        self._notify_buffer: bytearray = bytearray()
        self._on_disconnect_cb = on_disconnect
        self._chunk_size_override = chunk_size
        self._chunk_delay_override = chunk_delay
        self._max_payload: Optional[int] = None
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    #  Tunables
    # ------------------------------------------------------------------ #

    @property
    def chunk_delay(self) -> float:
        """Pause in seconds between two chunks."""
        if self._chunk_delay_override is not None:
            return self._chunk_delay_override
        return self.CHUNK_DELAY

    def _effective_chunk(self, default: int) -> int:
        """Chunk size: the instance override (else ``default``), capped to the payload limit."""
        size = self._chunk_size_override if self._chunk_size_override is not None else default
        if self._max_payload is not None:
            size = min(size, self._max_payload)
        return max(1, size)

    @property
    def chunk_size(self) -> int:
        """Bytes per chunk for plain writes."""
        return self._effective_chunk(self.CHUNK_SIZE)

    @property
    def chunk_size_raster(self) -> int:
        """Bytes per chunk for raster strips."""
        return self._effective_chunk(self.CHUNK_SIZE_RASTER)

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

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

        # Forget everything learned from a previous connection.
        self._notify_char = None
        self._notify_buffer.clear()
        self._max_payload = None

        self._client = BleakClient(address, disconnected_callback=self._on_disconnect_cb)
        await self._client.connect()
        try:
            self._write_char = await self._find_write_characteristic()
        except BaseException:
            # Do not leak a half-initialised connection (e.g. start_notify failed).
            await self._client.disconnect()
            raise
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
        captures any incoming responses. Also records the largest payload
        the BLE stack reports for write-without-response, so chunks never
        exceed it.

        :returns: UUID of the write characteristic, or ``None`` when none
            is found.
        """
        assert self._client is not None
        write_char = None
        write_obj = None
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
                    write_obj = char
                    continue
                if write_char is None:
                    if "write-without-response" in char.properties or "write" in char.properties:
                        if service.uuid.lower() in (
                            BLE_SERVICE_UUID.lower(),
                            BLE_SERVICE_UUID_ALT.lower(),
                        ):
                            write_char = char.uuid
                            write_obj = char

        if self._notify_char:
            await self._client.start_notify(self._notify_char, self._on_notify)

        self._max_payload = self._read_max_payload(write_obj)
        return write_char

    @classmethod
    def _read_max_payload(cls, char) -> Optional[int]:
        """Return the stack's negotiated write-without-response limit, if known.

        A value of 20 is the default before the MTU exchange completes (and
        the constant BlueZ < 5.62 reports), so it is treated as "unknown"
        and the configured chunk sizes apply unchanged.
        """
        size = getattr(char, "max_write_without_response_size", None)
        if isinstance(size, int) and size > cls._DEFAULT_MAX_PAYLOAD:
            return size
        return None

    def _on_notify(self, _sender, data: bytearray) -> None:
        """Callback for inbound notifications (e.g. responses to ``GS I``)."""
        self._notify_buffer.extend(data)
        overflow = len(self._notify_buffer) - self._NOTIFY_BUFFER_LIMIT
        if overflow > 0:
            del self._notify_buffer[:overflow]

    async def disconnect(self) -> None:
        """Disconnect from the printer and release all references."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._write_char = None
        self._notify_char = None
        self._notify_buffer.clear()
        self._max_payload = None

    @property
    def is_connected(self) -> bool:
        """Whether the BLE client is currently connected."""
        return bool(self._client and self._client.is_connected)

    @property
    def has_notify(self) -> bool:
        """Whether the remote device exposes a notify characteristic."""
        return self._notify_char is not None

    # ------------------------------------------------------------------ #
    #  Writing
    # ------------------------------------------------------------------ #

    async def write(self, data: bytes) -> None:
        """Send raw bytes over BLE with MTU chunking and pacing.

        The whole payload is sent under a lock, so concurrent writers
        cannot interleave their chunks.

        :param data: Bytes to send.
        :raises RuntimeError: When the transport is not connected.
        """
        if not self.is_connected:
            raise RuntimeError("BLE transport is not connected.")
        assert self._client is not None
        assert self._write_char is not None
        size = self.chunk_size
        delay = self.chunk_delay
        async with self._write_lock:
            for i in range(0, len(data), size):
                chunk = data[i : i + size]
                await self._client.write_gatt_char(
                    self._write_char, chunk, response=False
                )
                await asyncio.sleep(delay)

    async def write_raster_strip(self, data: bytes, rows: int = 24) -> None:
        """Send one raster strip in :attr:`chunk_size_raster`-byte chunks.

        Chunks are counted from the start of the payload, header included,
        so they do not coincide with raster rows; the printer reassembles
        the byte stream and does not care. After all chunks are sent,
        sleeps ``max(0.05, rows * 0.002)`` seconds so the paper motor can
        advance before the next strip is issued. Like :meth:`write`, the
        strip is sent under the write lock.

        :param data: A complete ``GS v 0`` strip payload as returned by
            :func:`~goojprt.raster.image_to_raster_strips`.
        :param rows: Number of raster rows in this strip (used to compute
            the post-strip throttle). Defaults to 24.
        :raises RuntimeError: When the transport is not connected.
        """
        if not self.is_connected:
            raise RuntimeError("BLE transport is not connected.")
        assert self._client is not None
        assert self._write_char is not None
        size = self.chunk_size_raster
        delay = self.chunk_delay
        async with self._write_lock:
            for i in range(0, len(data), size):
                chunk = data[i : i + size]
                await self._client.write_gatt_char(
                    self._write_char, chunk, response=False
                )
                await asyncio.sleep(delay)
            await asyncio.sleep(max(0.05, rows * 0.002))

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
        assert self._client is not None
        return bytes(await self._client.read_gatt_char(uuid))
