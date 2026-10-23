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

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from goojprt import commands, raster, rendering, status
from goojprt.constants import PAPER_WIDTH_PX
from goojprt.encoding import CODEPAGE_TO_ENCODING
from goojprt.enums import Align, CodePage, TextSize
from goojprt.profile import CANDIDATES, CANDIDATE_LETTERS, CZECH_TEST_TEXT, TextProfile
from goojprt.transport import BleTransport, PreviewTransport, SppTransport

log = logging.getLogger(__name__)


def _identity_text(response: bytes) -> str:
    """Printable text of a ``GS I 65–68`` answer.

    The answers come with a one-character marker in front (``_`` in the Epson
    manual; ``-`` or none were seen on a PT-210) and NUL padding; both are
    dropped.
    """
    try:
        text = "".join(ch for ch in response.decode("ascii", errors="ignore") if ch.isprintable()).strip()
    except Exception:  # noqa: BLE001 — a malformed answer is "no answer", never an error
        return ""
    return text[1:] if text[:1] in ("_", "-") else text


async def disconnect_quietly(printer) -> None:
    """Disconnect ``printer`` and log a failure instead of raising it.

    Meant for ``finally`` blocks: a failing disconnect must not replace the
    exception that is already on its way out.
    """
    try:
        await printer.disconnect()
    except Exception:  # noqa: BLE001
        log.warning("disconnecting the printer failed", exc_info=True)


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
        self._ble: BleTransport | PreviewTransport | None = None
        self._spp: SppTransport | None = None
        self._profile: TextProfile | None = None
        self._text_encoding: str | None = None

    @classmethod
    @asynccontextmanager
    async def ble(
        cls,
        address: str,
        *,
        initialize: bool = True,
        on_disconnect=None,
        chunk_size: int | None = None,
        chunk_delay: float | None = None,
    ) -> AsyncIterator["GoojPrtPT210"]:
        """Connect over BLE for the duration of an ``async with`` block.

        The printer is initialised (``ESC @``, unless ``initialize=False``)
        and always disconnected on the way out, also when the block raises::

            async with GoojPrtPT210.ble("XX:XX:XX:XX:XX:XX") as printer:
                await printer.print_text("Hello")

        The remaining parameters are those of :meth:`connect_ble`.
        """
        printer = cls()
        await printer.connect_ble(
            address, on_disconnect=on_disconnect,
            chunk_size=chunk_size, chunk_delay=chunk_delay,
        )
        try:
            if initialize:
                await printer.initialize()
            yield printer
        finally:
            await disconnect_quietly(printer)

    @classmethod
    @contextmanager
    def spp(
        cls, address: str, port: int = 1, *, initialize: bool = True,
    ) -> Iterator["GoojPrtPT210"]:
        """Connect over classic SPP (Linux only) for the duration of a ``with`` block.

        Initialises the printer unless ``initialize=False`` and always closes
        the socket afterwards::

            with GoojPrtPT210.spp("XX:XX:XX:XX:XX:XX") as printer:
                printer.print_text_spp("Hello")
        """
        printer = cls()
        printer.connect_spp(address, port)
        try:
            if initialize:
                printer.initialize_spp()
            yield printer
        finally:
            try:
                printer.disconnect_spp()
            except Exception:  # noqa: BLE001
                log.warning("closing the SPP socket failed", exc_info=True)

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

    async def connect_ble(
        self,
        address: str,
        *,
        on_disconnect=None,
        chunk_size: int | None = None,
        chunk_delay: float | None = None,
    ) -> None:
        """Connect to the printer over BLE.

        Creates the BLE transport lazily on first use.

        :param on_disconnect: Callback invoked when the link drops.
        :param chunk_size: Bytes per BLE write; see
            :class:`~goojprt.transport.ble.BleTransport`.
        :param chunk_delay: Pause between writes in seconds. Lower it to
            print faster if your unit keeps up, raise it if bytes get lost.

        ``on_disconnect``, ``chunk_size`` and ``chunk_delay`` apply when the
        transport is created, i.e. on the first connect. A preview transport
        attached with :meth:`connect_preview` is replaced by a real one, so
        printing can never silently go into the preview.
        """
        if self._ble is None or isinstance(self._ble, PreviewTransport):
            kwargs = {}
            if chunk_size is not None:
                kwargs["chunk_size"] = chunk_size
            if chunk_delay is not None:
                kwargs["chunk_delay"] = chunk_delay
            self._ble = BleTransport(on_disconnect=on_disconnect, **kwargs)
        await self._ble.connect(address)

    def _require_ble(self) -> BleTransport | PreviewTransport:
        """Return the BLE transport or explain how to get one."""
        if self._ble is None:
            raise RuntimeError("Not connected over BLE; call connect_ble() first.")
        return self._ble

    def _require_spp(self) -> SppTransport:
        """Return the SPP transport or explain how to get one."""
        if self._spp is None:
            raise RuntimeError("Not connected over SPP; call connect_spp() first.")
        return self._spp

    def connect_preview(self) -> PreviewTransport:
        """Attach a :class:`~goojprt.transport.preview.PreviewTransport` instead of a printer.

        Every BLE-style method (``print_text_image``, ``print_image``,
        ``print_pdf417``, templates, …) then renders into memory instead of
        printing; read the result from the returned transport::

            preview = printer.connect_preview()
            await printer.print_text_image("Hello")
            preview.save("preview.png")

        Native ESC/POS text and QR codes appear only as dashed notes.

        :raises RuntimeError: While a BLE connection is open — it would be
            orphaned; call :meth:`disconnect` first.
        """
        current = self._ble
        if (current is not None and not isinstance(current, PreviewTransport)
                and current.is_connected):
            raise RuntimeError("connect_preview(): a BLE connection is open; call disconnect() first.")
        transport = PreviewTransport()
        self._ble = transport
        return transport

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
        """Initialise the printer (``ESC @``) — reset to factory defaults.

        A profile set with :meth:`apply_profile` is sent again straight after
        the reset (in the same write), so it survives re-initialisation and
        reconnects. Without one, the remembered text encoding is forgotten
        along with the printer's code page.
        """
        data = commands.init()
        encoding = None
        if self._profile is not None:
            data += self._profile_bytes(self._profile)
            encoding = self._profile.encoding
        await self._require_ble().write(data)
        self._text_encoding = encoding

    @property
    def text_encoding(self) -> str | None:
        """Codec :meth:`print_text` uses when no ``encoding`` is given, or ``None`` (GB2312)."""
        return self._text_encoding

    @staticmethod
    def _profile_bytes(profile: TextProfile) -> bytes:
        """``[FS .] ESC t n`` for ``profile``."""
        prefix = commands.chinese_mode(False) if profile.chinese_mode_off else b""
        return prefix + commands.charset(profile.code_page)

    async def apply_profile(self, profile: TextProfile) -> None:
        """Select the profile's code page now and after every :meth:`initialize`.

        Afterwards :meth:`print_text` encodes with the profile's codec by
        default, so native text with diacritics needs no ``encoding=`` and no
        bitmap rendering. Find a profile with ``goojprt <addr> --calibrate``.
        """
        await self._require_ble().write(self._profile_bytes(profile))
        self._profile = profile
        self._text_encoding = profile.encoding

    async def clear_profile(self) -> None:
        """Forget the profile and reset the printer to its defaults."""
        self._profile = None
        await self.initialize()

    async def use_codepage(
        self,
        code_page: "CodePage | int",
        *,
        chinese_mode_off: bool = True,
        encoding: str | None = None,
    ) -> None:
        """Shortcut for :meth:`apply_profile` with a code page and its usual codec.

        :param code_page: ``ESC t`` table, e.g. ``CodePage.PC852``.
        :param chinese_mode_off: Send ``FS .`` first (see :meth:`set_chinese_mode`).
        :param encoding: Codec for the table; defaults to the one known for
            ``code_page``.
        :raises ValueError: When no codec is known for the table and none is given.
        """
        if encoding is None:
            encoding = CODEPAGE_TO_ENCODING.get(int(code_page))
            if encoding is None:
                raise ValueError(f"no codec is known for code page {int(code_page)}; pass encoding=")
        await self.apply_profile(TextProfile(int(code_page), encoding, chinese_mode_off))

    async def print_text(
        self,
        text: str,
        align: Align = Align.LEFT,
        bold: bool = False,
        underline: bool = False,
        size: TextSize = TextSize.NORMAL,
        newline: bool = True,
        encoding: str | None = None,
    ) -> None:
        """Print formatted text over BLE using the native ESC/POS engine.

        :param text: String to print.
        :param align: Horizontal alignment.
        :param bold: Enable emphasised printing.
        :param underline: Enable underlined printing.
        :param size: Character size multiplier.
        :param newline: Append a trailing line feed after the text.
        :param encoding: Python codec name used for byte encoding. Defaults to
            the codec of the active profile / :meth:`set_charset`, else GB2312.
        """
        await self._require_ble().write(commands.build_text_block(
            text, align, bold, underline, size, newline,
            encoding or self._text_encoding or "gb2312",
        ))

    def _can_print_natively(self, line: str) -> bool:
        """Whether ``line`` survives the active native encoding unchanged."""
        if line.isascii():
            return True
        if self._text_encoding is None:
            return False
        try:
            line.encode(self._text_encoding)
        except UnicodeEncodeError:
            return False
        return True

    async def print_text_auto(
        self,
        text: str,
        align: Align = Align.LEFT,
        bold: bool = False,
        underline: bool = False,
        size: TextSize = TextSize.NORMAL,
        font_size: int = 24,
    ) -> None:
        """Print each line natively when the active code page can show it, else as a bitmap.

        With a profile for your language (:meth:`apply_profile`) ordinary text
        with diacritics prints natively — fast and small — while a line that
        contains a character the table lacks (a euro sign in CP852, say) is
        rendered as a bitmap instead of printing garbage. Without a profile
        only plain ASCII goes the native way. ``bold``, ``underline`` and
        ``size`` apply to native lines only; ``font_size`` to bitmap lines.
        """
        for line in text.split("\n"):
            if self._can_print_natively(line):
                await self.print_text(line, align, bold, underline, size)
            else:
                await self.print_text_image(line, font_size=font_size, align=align)

    async def print_line(self, char: str = "-", encoding: str = "ascii") -> None:
        """Print a horizontal rule built from a repeated character.

        Defaults to roughly 32 characters wide — ``PAPER_WIDTH_PX // 12``,
        matching Font A metrics.
        """
        line = char * (PAPER_WIDTH_PX // 12)  # approximate column count
        await self.print_text(line, encoding=encoding)

    async def feed(self, lines: int = 3) -> None:
        """Feed paper by ``lines`` rows (``ESC d n``)."""
        await self._require_ble().write(commands.feed(lines))

    async def cut(self) -> None:
        """Trigger the cutter (no-op on PT-210, which has no cutter hardware)."""
        await self._require_ble().write(commands.cut())

    async def print_qr(
        self,
        data: str,
        size: int = 6,
        align: Align = Align.CENTER,
        error_correction: int = 1,
    ) -> None:
        """Print a QR code over BLE using the native ESC/POS QR command."""
        await self._require_ble().write(commands.build_qr_block(data, size, align, error_correction))

    async def print_image(self, image, strip_height: int = 24) -> None:
        """Print a :class:`PIL.Image.Image` over BLE as an ESC/POS raster.

        The image is split into horizontal strips of ``strip_height`` rows and
        sent as separate ``GS v 0`` commands. This keeps each payload small
        enough to fit in the printer's limited buffer; the transport paces
        the writes and waits after every strip for the paper motor.

        Rasterising runs in a worker thread so a large image does not stall
        the event loop (and with it BLE keep-alives and notifications).

        :param image: PIL image in any mode.
        :param strip_height: Rows per strip (default 24 → 1 152 bytes per
            strip, safe for cheap hardware with small buffers).
        """
        ble = self._require_ble()
        strips = await asyncio.to_thread(
            raster.image_to_raster_strips, image, strip_height=strip_height,
        )
        for strip in strips:
            rows = strip[6] | (strip[7] << 8)  # from GS v 0 header
            await ble.write_raster_strip(strip, rows=rows)

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
        wrap: bool = True,
    ) -> None:
        """Print text as an antialiased bitmap (full Unicode / diacritics).

        Unlike :meth:`print_text`, this method does not depend on the
        firmware code page: the text is rendered via PIL with LANCZOS
        resampling and Floyd–Steinberg dithering, so any installed font
        produces a readable result. Lines wider than the paper are
        word-wrapped unless ``wrap`` is ``False``.
        """
        img = await asyncio.to_thread(
            rendering.render_text_image,
            text, font_size=font_size, font_path=font_path,
            line_spacing=line_spacing, padding=padding, align=align,
            supersample=supersample, dither=dither, threshold=threshold,
            wrap=wrap,
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
        img = await asyncio.to_thread(
            rendering.render_grid,
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
        img = await asyncio.to_thread(
            rendering.render_pdf417,
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
        img = await asyncio.to_thread(
            rendering.render_ekg,
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
        await self._require_ble().write(commands.charset(code_page))
        self._text_encoding = CODEPAGE_TO_ENCODING.get(int(code_page))

    async def set_chinese_mode(self, enabled: bool) -> None:
        """Enter (``FS &``) or cancel (``FS .``) the double-byte Chinese mode.

        Printers that boot in GB18030 mode treat bytes ≥ 0x80 as half of a
        two-byte character, which can garble single-byte code pages even
        after :meth:`set_charset`. Cancelling the mode first may fix that;
        :meth:`probe_charsets` prints each page with and without it so you
        can see whether your unit cares. ``ESC @`` (:meth:`initialize`)
        resets the printer, so call this afterwards.
        """
        await self._require_ble().write(commands.chinese_mode(enabled))

    async def set_density(
        self,
        level: "str | int" = "normal",
        *,
        dots: int = 7,
        interval: int = 2,
    ) -> None:
        """Set the print darkness (``ESC 7``): heating time, dots and interval.

        :param level: ``"light"``, ``"normal"`` or ``"dark"``, or a heating
            time 0–255 (see :data:`goojprt.commands.DENSITY_PRESETS`; the
            presets are uncalibrated starting points). Darker output costs
            battery and speed.
        :param dots: Maximum simultaneously heated dots, 0–255.
        :param interval: Heating interval, 0–255.
        :raises ValueError: For an unknown preset or an out-of-range value;
            nothing is sent in that case.

        ``ESC @`` (:meth:`initialize`) resets the heating parameters, so call
        this afterwards. Whether a given unit honours ``ESC 7`` is not
        verified.
        """
        heating = commands.resolve_density(level)
        await self._require_ble().write(
            commands.energy(dots=dots, heating=heating, interval=interval)
        )

    async def query_printer_info(self, timeout: float = 2.0) -> dict:
        """Query identification data via ``GS I``.

        ``GS I 1 / 2 / 3`` answer with a single *ID byte* each (Epson: model,
        type, ROM version), not text, so ``model_id``, ``printer_type`` and
        ``firmware`` are only roughly readable; ``raw_responses`` holds the
        bytes. ``GS I 65 – 68`` answer with text and fill ``firmware_version``,
        ``manufacturer``, ``model_name`` and ``serial_number``; keys the
        printer does not answer are left out. The PT-210 answers all of them.

        :param timeout: Total time budget, shared by all queries.
        :returns: A dictionary with the keys above and ``raw_responses`` — or
            ``{"error": ...}`` when the printer does not expose a notify
            characteristic.
        """
        ble = self._require_ble()
        if not ble.has_notify:
            return {"error": "Printer has no notify characteristic; responses cannot be read."}

        results = {}
        # Epson numbers these 1 = model, 2 = type, 3 = ROM version; the
        # mapping below predates that check and is kept for compatibility.
        queries = {
            "model_id":     commands.info_request(1),
            "printer_type": commands.info_request(3),
            "firmware":     commands.info_request(2),
        }
        identity_queries = {
            "firmware_version": commands.info_request(65),
            "manufacturer":     commands.info_request(66),
            "model_name":       commands.info_request(67),
            "serial_number":    commands.info_request(68),
        }
        per_query = timeout / (len(queries) + len(identity_queries))

        raw_responses = []
        for key, cmd in queries.items():
            ble.clear_notify_buffer()
            await ble.write(cmd)
            response = await ble.read_notify(per_query)
            raw_responses.append(list(response))
            try:
                results[key] = response.decode("ascii", errors="replace").strip("\x00").strip()
            except Exception:
                results[key] = response.hex()

        for key, cmd in identity_queries.items():
            ble.clear_notify_buffer()
            await ble.write(cmd)
            text = _identity_text(await ble.read_notify(per_query))
            if text:
                results[key] = text

        results["raw_responses"] = raw_responses
        return results

    async def query_full_info(self, timeout: float = 1.5) -> dict:
        """Read BLE Device Info (0x180A) + Battery (0x180F) + ESC/POS status + ``GS I``.

        :returns: A dictionary with keys ``ble_device``, ``ble_battery``,
            ``escpos_status`` and ``escpos_info``. Every ``escpos_status``
            entry (``printer``, ``offline``, ``error``, ``paper``) holds the
            ``raw`` response byte, an ``ok`` verdict and the decoded
            ``flags`` (see :mod:`goojprt.status`).
        """
        ble = self._require_ble()
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
                raw = await ble.read_gatt(uuid)
                if key == "system_id":
                    ble_device[key] = raw.hex(":")
                else:
                    ble_device[key] = raw.decode("utf-8", errors="replace").strip("\x00").strip()
            except Exception:
                pass
        info["ble_device"] = ble_device

        battery: dict = {}
        try:
            raw = await ble.read_gatt("00002a19-0000-1000-8000-00805f9b34fb")
            battery["level_pct"] = raw[0]
        except Exception:
            pass
        info["ble_battery"] = battery

        escpos_status: dict = {}
        if ble.has_notify:
            dle_queries = {
                "printer": status.PRINTER,
                "offline": status.OFFLINE_CAUSE,
                "error":   status.ERROR_CAUSE,
                "paper":   status.PAPER_SENSOR,
            }
            for key, n in dle_queries.items():
                ble.clear_notify_buffer()
                await ble.write(commands.status_request(n))
                response = await ble.read_notify(timeout / len(dle_queries))
                if response:
                    byte = response[0]
                    escpos_status[key] = {
                        "raw":   byte,
                        "ok":    status.status_ok(n, byte),
                        "flags": status.decode_status(n, byte),
                    }
        info["escpos_status"] = escpos_status

        escpos_info = await self.query_printer_info(timeout=timeout)
        escpos_info.pop("raw_responses", None)
        info["escpos_info"] = escpos_info

        return info

    async def print_charset_calibration(
        self,
        text: str = CZECH_TEST_TEXT,
        candidates: "tuple[TextProfile, ...] | list[TextProfile]" = CANDIDATES,
    ) -> dict[str, TextProfile]:
        """Print ``text`` once per candidate profile, each line labelled with a letter.

        Look at the paper and pick the letter whose line shows ``text``
        exactly; the returned mapping turns it back into a
        :class:`~goojprt.profile.TextProfile` that :meth:`apply_profile`
        accepts. Every line starts from a fresh ``ESC @``; the previously
        applied profile (if any) is restored at the end.

        :returns: ``{letter: profile}`` in the order printed.
        """
        ble = self._require_ble()
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if len(candidates) > len(letters):
            raise ValueError(f"at most {len(letters)} candidates fit on one sheet")
        sheet = dict(zip(letters, candidates))

        await self.print_text_image("NATIVNI TEXT - KALIBRACE", font_size=20,
                                    align=Align.CENTER, wrap=False)
        for letter, profile in sheet.items():
            await self.print_text_image(f"{letter}: {profile.describe()}",
                                        font_size=16, wrap=False, padding=2)
            data = commands.init()
            data += self._profile_bytes(profile)
            data += text.encode(profile.encoding, errors="replace") + b"\n"
            await ble.write(data)
        await self.initialize()          # back to the active profile (or the defaults)
        await self.feed(3)
        return sheet

    async def probe_charsets(
        self,
        test_string: str = "Příliš žluťoučký kůň",
        pages: list[CodePage] | None = None,
        *,
        try_chinese_mode_off: bool = True,
    ) -> None:
        """Print ``test_string`` using each code page plus a bitmap reference.

        Useful for verifying which code pages the firmware actually
        ships — compare the native outputs against the always-correct
        bitmap row at the bottom.

        Each page is printed after a fresh ``ESC @`` (an applied profile is
        not sent again until the end). With
        ``try_chinese_mode_off`` (the default) every page is printed twice,
        the second time after ``FS .`` — if only the second variant is
        readable, call :meth:`set_chinese_mode` with ``False`` before
        printing native text on your unit.
        """
        from goojprt.encoding import CODEPAGE_TO_ENCODING

        if pages is None:
            pages = [CodePage.PC437, CodePage.PC850, CodePage.PC852,
                     CodePage.WPC1250, CodePage.WPC1250_STD, CodePage.PC858]

        ble = self._require_ble()
        await self.initialize()
        await self.print_text_image("=== PROBE CHARSETS ===",
                                    align=Align.CENTER, font_size=20)

        variants = (False, True) if try_chinese_mode_off else (False,)
        for cp in pages:
            encoding = CODEPAGE_TO_ENCODING.get(cp, "latin-1")
            try:
                encoded = test_string.encode(encoding, errors="replace")
            except LookupError:
                encoded = test_string.encode("latin-1", errors="replace")
            for chinese_off in variants:
                suffix = " + FS ." if chinese_off else ""
                await self.print_text_image(
                    f"-- CodePage.{cp.name} (ESC t {cp.value}){suffix} --",
                    font_size=18, align=Align.LEFT,
                )
                # A raw ESC @, not initialize(): that would send an applied profile's
                # FS . and ESC t again and spoil the "without FS ." variant.
                await ble.write(commands.init())
                if chinese_off:
                    await ble.write(commands.chinese_mode(False))
                await ble.write(commands.charset(cp))
                await ble.write(encoded + b"\n")

        await self.initialize()          # back to the active profile (or the defaults)
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
        self._require_spp().write(commands.init())

    def print_text_spp(
        self,
        text: str,
        align: Align = Align.LEFT,
        bold: bool = False,
        underline: bool = False,
        size: TextSize = TextSize.NORMAL,
        newline: bool = True,
        encoding: str | None = None,
    ) -> None:
        """Print text over SPP (shares :func:`commands.build_text_block` with BLE)."""
        self._require_spp().write(commands.build_text_block(
            text, align, bold, underline, size, newline,
            encoding or self._text_encoding or "gb2312",
        ))

    def feed_spp(self, lines: int = 3) -> None:
        """Feed paper over SPP."""
        self._require_spp().write(commands.feed(lines))

    def cut_spp(self) -> None:
        """Trigger the cutter over SPP (no-op on PT-210)."""
        self._require_spp().write(commands.cut())

    def print_qr_spp(
        self,
        data: str,
        size: int = 6,
        align: Align = Align.CENTER,
        error_correction: int = 1,
    ) -> None:
        """Print a QR code over SPP (shares :func:`commands.build_qr_block`)."""
        self._require_spp().write(commands.build_qr_block(data, size, align, error_correction))

    def print_image_spp(self, image, strip_height: int = 24) -> None:
        """Print a :class:`PIL.Image.Image` over SPP as an ESC/POS raster.

        :param image: PIL image in any mode.
        :param strip_height: Rows per strip (default 24).
        """
        for strip in raster.image_to_raster_strips(image, strip_height=strip_height):
            rows = strip[6] | (strip[7] << 8)  # from GS v 0 header
            self._require_spp().write_raster_strip(strip, rows=rows)

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
