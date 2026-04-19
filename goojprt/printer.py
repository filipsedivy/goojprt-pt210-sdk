"""High-level SDK facade for the GoojPrt PT-210 thermal printer.

:class:`GoojPrtPT210` is the entry point of the SDK. It owns both
transports (BLE / SPP), composes :mod:`goojprt.commands`,
:mod:`goojprt.raster` and :mod:`goojprt.rendering` into an ergonomic
API, and exposes a dual set of methods:

* **BLE (async)** — ``connect_ble`` / ``print_text`` / ``print_image``
  / … . This is the primary, cross-platform path.
* **SPP (sync, Linux only)** — ``connect_spp`` / ``print_text_spp`` /
  … . Preserved for callers that need classic RFCOMM.

The two API surfaces share the underlying byte builders so their output
is byte-identical.
"""

from goojprt import commands, raster, rendering
from goojprt.enums import Align, CodePage, TextSize
from goojprt.transport import BleTransport, SppTransport


class GoojPrtPT210:
    """Driver for the GoojPrt PT-210 thermal printer (48 mm / 384 px head).

    Supports BLE (async, cross-platform, primary) and classic Bluetooth
    SPP (sync, Linux only). Both API surfaces are exposed side-by-side
    for backward compatibility.

    Example (BLE)::

        import asyncio
        from goojprt import GoojPrtPT210

        async def main() -> None:
            printer = GoojPrtPT210()
            await printer.connect_ble("XX:XX:XX:XX:XX:XX")
            await printer.initialize()
            await printer.print_text("Hello, world!")
            await printer.feed(3)
            await printer.disconnect()

        asyncio.run(main())
    """

    def __init__(self) -> None:
        """Create an empty driver. Transports are attached on first connect."""
        self._ble: BleTransport | None = None
        self._spp: SppTransport | None = None

    # ------------------------------------------------------------------ #
    #  BLE lifecycle
    # ------------------------------------------------------------------ #

    async def scan_ble(self, timeout: float = 10.0) -> list[dict]:
        """Discover nearby BLE devices.

        :param timeout: Scan duration in seconds.
        :returns: List of ``{"name", "address"}`` dictionaries.
        """
        if self._ble is None:
            self._ble = BleTransport()
        return await self._ble.scan(timeout=timeout)

    async def connect_ble(self, address: str, *, on_disconnect=None) -> None:
        """Connect to the printer over BLE.

        Creates the BLE transport lazily on first use.
        """
        if self._ble is None:
            self._ble = BleTransport(on_disconnect=on_disconnect)
        await self._ble.connect(address)

    async def disconnect(self) -> None:
        """Disconnect the BLE client (see :meth:`BleTransport.disconnect`)."""
        if self._ble is not None:
            await self._ble.disconnect()

    @property
    def is_connected_ble(self) -> bool:
        """Whether the BLE transport is currently connected."""
        return self._ble is not None and self._ble.is_connected

    # ------------------------------------------------------------------ #
    #  SPP lifecycle
    # ------------------------------------------------------------------ #

    def connect_spp(self, address: str, port: int = 1) -> None:
        """Connect to the printer over classic Bluetooth SPP (Linux only)."""
        if self._spp is None:
            self._spp = SppTransport()
        self._spp.connect(address, port)

    def disconnect_spp(self) -> None:
        """Close the SPP socket."""
        if self._spp is not None:
            self._spp.disconnect()

    @property
    def is_connected_spp(self) -> bool:
        """Whether the SPP socket is currently open."""
        return self._spp is not None and self._spp.is_connected

    # ------------------------------------------------------------------ #
    #  BLE high-level API
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        """Initialise the printer (``ESC @``) — reset to factory defaults."""
        await self._ble.write(commands.init())

    async def print_text(
        self,
        text: str,
        align: Align = Align.LEFT,
        bold: bool = False,
        underline: bool = False,
        size: TextSize = TextSize.NORMAL,
        newline: bool = True,
        encoding: str = "gb2312",
    ) -> None:
        """Print formatted text over BLE using the native ESC/POS engine.

        :param text: String to print.
        :param align: Horizontal alignment.
        :param bold: Enable emphasised printing.
        :param underline: Enable underlined printing.
        :param size: Character size multiplier.
        :param newline: Append a trailing line feed after the text.
        :param encoding: Python codec name used for byte encoding.
        """
        await self._ble.write(commands.build_text_block(
            text, align, bold, underline, size, newline, encoding,
        ))

    async def print_line(self, char: str = "-", encoding: str = "ascii") -> None:
        """Print a horizontal rule built from a repeated character.

        Defaults to roughly 32 characters wide — ``PAPER_WIDTH_PX // 12``,
        matching Font A metrics.
        """
        line = char * (384 // 12)  # PAPER_WIDTH_PX // 12 — approximate column count
        await self.print_text(line, encoding=encoding)

    async def feed(self, lines: int = 3) -> None:
        """Feed paper by ``lines`` rows (``ESC d n``)."""
        await self._ble.write(commands.feed(lines))

    async def cut(self) -> None:
        """Trigger the cutter (no-op on PT-210, which has no cutter hardware)."""
        await self._ble.write(commands.cut())

    async def print_qr(
        self,
        data: str,
        size: int = 6,
        align: Align = Align.CENTER,
        error_correction: int = 1,
    ) -> None:
        """Print a QR code over BLE using the native ESC/POS QR command."""
        await self._ble.write(commands.build_qr_block(data, size, align, error_correction))

    async def print_image(self, image, strip_height: int = 24) -> None:
        """Print a :class:`PIL.Image.Image` over BLE as an ESC/POS raster.

        The image is split into horizontal strips of ``strip_height`` rows and
        sent as separate ``GS v 0`` commands. This keeps each payload small
        enough to fit in the printer's limited buffer and aligns chunk
        boundaries to raster row width, preventing pixel-shift artifacts.

        :param image: PIL image in any mode.
        :param strip_height: Rows per strip (default 24 → 1 152 bytes per
            strip, safe for cheap hardware with small buffers).
        """
        for strip in raster.image_to_raster_strips(image, strip_height=strip_height):
            rows = strip[6] | (strip[7] << 8)  # from GS v 0 header
            await self._ble.write_raster_strip(strip, rows=rows)

    async def print_image_from_file(self, path: str) -> None:
        """Load an image from disk (via :func:`PIL.Image.open`) and print it."""
        from PIL import Image
        await self.print_image(Image.open(path))

    async def print_text_image(
        self,
        text: str,
        font_size: int = 24,
        font_path: str | None = None,
        align: Align = Align.LEFT,
        line_spacing: int = 6,
        padding: int = 8,
        supersample: int = 3,
        dither: bool = True,
        threshold: int = 140,
    ) -> None:
        """Print text as an antialiased bitmap (full Unicode / diacritics).

        Unlike :meth:`print_text`, this method does not depend on the
        firmware code page: the text is rendered via PIL with LANCZOS
        resampling and Floyd–Steinberg dithering, so any installed font
        produces a readable result.
        """
        img = rendering.render_text_image(
            text, font_size=font_size, font_path=font_path,
            line_spacing=line_spacing, padding=padding, align=align,
            supersample=supersample, dither=dither, threshold=threshold,
        )
        await self.print_image(img)

    async def print_grid(
        self,
        columns: list[dict],
        font_size: int = 22,
        font_path: str | None = None,
        padding: int = 6,
        supersample: int = 3,
        dither: bool = False,
        threshold: int = 128,
    ) -> None:
        """Print a single row of a multi-column table over BLE.

        See :func:`goojprt.rendering.grid.render_grid` for the column
        dictionary schema.
        """
        img = rendering.render_grid(
            columns, font_size=font_size, font_path=font_path,
            padding=padding, supersample=supersample,
            dither=dither, threshold=threshold,
        )
        await self.print_image(img)

    async def print_pdf417(
        self,
        data: str,
        align: Align = Align.CENTER,
        scale: int = 2,
        row_height: int = 5,
        columns: int = 5,
        padding: int = 10,
        min_rows: int | None = None,
    ) -> None:
        """Print a PDF417 barcode over BLE.

        The barcode is rendered as a bitmap and padded to the full paper
        width according to ``align``.
        """
        img = rendering.render_pdf417(
            data, scale=scale, row_height=row_height,
            columns=columns, padding=padding, min_rows=min_rows,
        )
        img = raster.pad_image_to_paper_width(img, align)
        await self.print_image(img)

    async def print_ekg(
        self,
        beats: int = 4,
        height_px: int = 160,
        line_width: int = 2,
        grid: bool = True,
        grid_step_px: int = 32,
        amplitude: float = 0.82,
        portrait: bool = False,
        px_per_beat: int = 240,
    ) -> None:
        """Print a synthetic ECG waveform.

        ``portrait=True`` renders time running down the paper;
        ``portrait=False`` (default) renders time running across the
        paper width.
        """
        img = rendering.render_ekg(
            beats=beats, height_px=height_px, line_width=line_width,
            grid=grid, grid_step_px=grid_step_px, amplitude=amplitude,
            portrait=portrait, px_per_beat=px_per_beat,
        )
        await self.print_image(img)

    async def set_charset(self, code_page: CodePage) -> None:
        """Switch the printer's active code page (``ESC t n``).

        Note: this only works if the firmware actually ships the chosen
        table. For guaranteed diacritic support, use
        :meth:`print_text_image` instead.
        """
        await self._ble.write(commands.charset(code_page))

    async def query_printer_info(self, timeout: float = 2.0) -> dict:
        """Query model / firmware strings via ``GS I 1 / 2 / 3``.

        :returns: A dictionary with keys ``model_id``, ``firmware``,
            ``printer_type`` and ``raw_responses`` — or
            ``{"error": ...}`` when the printer does not expose a notify
            characteristic.
        """
        if not self._ble.has_notify:
            return {"error": "Printer has no notify characteristic; responses cannot be read."}

        results = {}
        queries = {
            "model_id":     bytes([0x1D, 0x49, 0x01]),
            "printer_type": bytes([0x1D, 0x49, 0x03]),
            "firmware":     bytes([0x1D, 0x49, 0x02]),
        }

        raw_responses = []
        for key, cmd in queries.items():
            self._ble.clear_notify_buffer()
            await self._ble.write(cmd)
            response = await self._ble.read_notify(timeout / len(queries))
            raw_responses.append(list(response))
            try:
                results[key] = response.decode("ascii", errors="replace").strip("\x00").strip()
            except Exception:
                results[key] = response.hex()

        results["raw_responses"] = raw_responses
        return results

    async def query_full_info(self, timeout: float = 1.5) -> dict:
        """Read BLE Device Info (0x180A) + Battery (0x180F) + ESC/POS status + ``GS I``.

        :returns: A dictionary with keys ``ble_device``, ``ble_battery``,
            ``escpos_status`` and ``escpos_info``.
        """
        info: dict = {}

        ble_device = {}
        ble_char_map = {
            "manufacturer":    "00002a29-0000-1000-8000-00805f9b34fb",
            "model_number":    "00002a24-0000-1000-8000-00805f9b34fb",
            "serial_number":   "00002a25-0000-1000-8000-00805f9b34fb",
            "hardware_rev":    "00002a27-0000-1000-8000-00805f9b34fb",
            "firmware_rev":    "00002a26-0000-1000-8000-00805f9b34fb",
            "software_rev":    "00002a28-0000-1000-8000-00805f9b34fb",
            "system_id":       "00002a23-0000-1000-8000-00805f9b34fb",
        }
        for key, uuid in ble_char_map.items():
            try:
                raw = await self._ble.read_gatt(uuid)
                if key == "system_id":
                    ble_device[key] = raw.hex(":")
                else:
                    ble_device[key] = raw.decode("utf-8", errors="replace").strip("\x00").strip()
            except Exception:
                pass
        info["ble_device"] = ble_device

        battery: dict = {}
        try:
            raw = await self._ble.read_gatt("00002a19-0000-1000-8000-00805f9b34fb")
            battery["level_pct"] = raw[0]
        except Exception:
            pass
        info["ble_battery"] = battery

        escpos_status: dict = {}
        if self._ble.has_notify:
            dle_queries = {
                "printer":  bytes([0x10, 0x04, 0x01]),
                "offline":  bytes([0x10, 0x04, 0x02]),
                "error":    bytes([0x10, 0x04, 0x03]),
                "paper":    bytes([0x10, 0x04, 0x04]),
            }
            for key, cmd in dle_queries.items():
                self._ble.clear_notify_buffer()
                await self._ble.write(cmd)
                response = await self._ble.read_notify(timeout / len(dle_queries))
                if response:
                    byte = response[0]
                    escpos_status[key] = {
                        "raw": byte,
                        "ok":  not bool(byte & 0b00101000),
                    }
        info["escpos_status"] = escpos_status

        escpos_info = await self.query_printer_info(timeout=timeout)
        escpos_info.pop("raw_responses", None)
        info["escpos_info"] = escpos_info

        return info

    async def probe_charsets(
        self,
        test_string: str = "Příliš žluťoučký kůň",
        pages: list[CodePage] | None = None,
    ) -> None:
        """Print ``test_string`` using each code page plus a bitmap reference.

        Useful for verifying which code pages the firmware actually
        ships — compare the native outputs against the always-correct
        bitmap row at the bottom.
        """
        from goojprt.encoding import CODEPAGE_TO_ENCODING

        if pages is None:
            pages = [CodePage.PC437, CodePage.PC850, CodePage.PC852,
                     CodePage.WPC1250, CodePage.PC858]

        await self.initialize()
        await self.print_text_image("=== PROBE CHARSETS ===",
                                    align=Align.CENTER, font_size=20)

        for cp in pages:
            encoding = CODEPAGE_TO_ENCODING.get(cp, "latin-1")
            await self.print_text_image(
                f"-- CodePage.{cp.name} (ESC t {cp.value}) --",
                font_size=18, align=Align.LEFT,
            )
            await self._ble.write(commands.charset(cp))
            try:
                encoded = test_string.encode(encoding, errors="replace")
            except LookupError:
                encoded = test_string.encode("latin-1", errors="replace")
            await self._ble.write(encoded + b"\n")

        await self.print_text_image(
            "=== Bitmap (always OK) ===\n" + test_string,
            font_size=22, align=Align.CENTER,
        )
        await self.feed(4)

    # ------------------------------------------------------------------ #
    #  SPP high-level API (synchronous, backward-compatible)
    # ------------------------------------------------------------------ #

    def initialize_spp(self) -> None:
        """Initialise the printer over SPP (``ESC @``)."""
        self._spp.write(commands.init())

    def print_text_spp(
        self,
        text: str,
        align: Align = Align.LEFT,
        bold: bool = False,
        underline: bool = False,
        size: TextSize = TextSize.NORMAL,
        newline: bool = True,
        encoding: str = "gb2312",
    ) -> None:
        """Print text over SPP (shares :func:`commands.build_text_block` with BLE)."""
        self._spp.write(commands.build_text_block(
            text, align, bold, underline, size, newline, encoding,
        ))

    def feed_spp(self, lines: int = 3) -> None:
        """Feed paper over SPP."""
        self._spp.write(commands.feed(lines))

    def cut_spp(self) -> None:
        """Trigger the cutter over SPP (no-op on PT-210)."""
        self._spp.write(commands.cut())

    def print_qr_spp(
        self,
        data: str,
        size: int = 6,
        align: Align = Align.CENTER,
        error_correction: int = 1,
    ) -> None:
        """Print a QR code over SPP (shares :func:`commands.build_qr_block`)."""
        self._spp.write(commands.build_qr_block(data, size, align, error_correction))

    def print_image_spp(self, image, strip_height: int = 24) -> None:
        """Print a :class:`PIL.Image.Image` over SPP as an ESC/POS raster.

        :param image: PIL image in any mode.
        :param strip_height: Rows per strip (default 24).
        """
        for strip in raster.image_to_raster_strips(image, strip_height=strip_height):
            rows = strip[6] | (strip[7] << 8)  # from GS v 0 header
            self._spp.write_raster_strip(strip, rows=rows)

    def print_pdf417_spp(
        self,
        data: str,
        align: Align = Align.CENTER,
        scale: int = 2,
        row_height: int = 5,
        columns: int = 5,
        padding: int = 10,
        min_rows: int | None = None,
    ) -> None:
        """Print a PDF417 barcode over SPP, padded to paper width per ``align``."""
        img = rendering.render_pdf417(
            data, scale=scale, row_height=row_height,
            columns=columns, padding=padding, min_rows=min_rows,
        )
        img = raster.pad_image_to_paper_width(img, align)
        self.print_image_spp(img)
