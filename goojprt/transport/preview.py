"""Preview transport: shows what would be printed, without a printer.

:class:`PreviewTransport` stands in for :class:`~goojprt.transport.ble.BleTransport`
and collects the byte stream instead of sending it. Raster strips (bitmap
text, images, PDF417, grids, EKG) are decoded back into pixels, ``ESC d n``
feeds become white space, and the result is available as a PIL image or PNG.

Native ESC/POS text and QR codes are produced by the printer firmware, so
they cannot be rendered here. They are never dropped silently: each one
shows up in the image as a dashed note with its content, and
:attr:`PreviewTransport.native_commands` counts them.
"""

import io
from os import PathLike
from typing import TYPE_CHECKING

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.raster import raster_to_image

if TYPE_CHECKING:
    from PIL import Image

_ESC_INIT = b"\x1b\x40"
_GS_V_0 = b"\x1d\x76\x30"
_ESC_FEED = b"\x1b\x64"

#: ``ESC`` commands (second byte) that take exactly one parameter byte.
_ESC_ONE_PARAM = b"aEd-t3M2"


def _describe_native(data: bytes) -> str | None:
    """Best-effort one-line description of a native ESC/POS command stream.

    Skips the formatting commands the SDK emits, shows the QR payload of a
    ``GS ( k`` symbol and the printable text of everything else. Unknown
    commands only make the text less accurate; nothing here can fail.

    :returns: ``None`` when the stream puts nothing on paper — code page,
        Chinese mode, density and similar settings — so previews stay quiet
        about it.
    """
    text: list[str] = []
    qr: str | None = None
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x1B and i + 1 < n:                       # ESC
            cmd = data[i + 1]
            if cmd == 0x37:                               # ESC 7 n1 n2 n3
                i += 5
            elif cmd == 0x40:                             # ESC @
                i += 2
            elif cmd in _ESC_ONE_PARAM:
                i += 3
            else:
                i += 2
        elif b == 0x1D and i + 1 < n:                     # GS
            cmd = data[i + 1]
            if cmd == 0x28 and data[i + 2:i + 3] == b"k" and i + 5 <= n:   # GS ( k pL pH ...
                length = data[i + 3] | (data[i + 4] << 8)
                body = data[i + 5:i + 5 + length]
                if body[:2] == b"\x31\x50":               # store QR payload
                    qr = body[3:].decode("utf-8", errors="replace")
                i += 5 + length
            elif cmd == 0x56 and data[i + 2:i + 3] in (b"A", b"B"):        # GS V m n
                i += 4
            else:                                         # GS ! n, GS I n, ...
                i += 3
        elif b == 0x1C:                                   # FS & / FS .
            i += 2
        elif b == 0x0A:
            text.append(" | ")
            i += 1
        else:
            if 32 <= b < 127:
                text.append(chr(b))
            elif b >= 0x80:
                text.append("?")                          # meaning depends on the code page
            i += 1
    label = f"QR {qr}" if qr is not None else "".join(text).strip(" |")
    if not label:
        return None
    return label if len(label) <= 60 else label[:57] + "..."


class PreviewTransport:
    """In-memory transport that records a print job and renders it.

    Duck-typed like :class:`~goojprt.transport.ble.BleTransport`; attach it to
    a facade with :meth:`~goojprt.printer.GoojPrtPT210.connect_preview`::

        printer = GoojPrtPT210()
        preview = printer.connect_preview()
        await printer.print_text_image("Příliš žluťoučký kůň")
        preview.save("preview.png")
        print(preview.summary())

    It is connected from the start; there is no BLE link, no notify
    characteristic and no GATT, so status queries come back empty.
    """

    #: Approximate paper advance of one line fed with ``ESC d n``, in pixels.
    FEED_LINE_PX = 30
    #: Height of the dashed note that stands in for a native command.
    NOTE_HEIGHT_PX = 20

    def __init__(self) -> None:
        """Create a connected, empty preview transport."""
        self._connected = True
        # Raster strips (images), feeds (white space, in pixels) and notes (str).
        self._parts: list["Image.Image | int | str"] = []
        #: Number of native ESC/POS commands that are shown as notes only.
        self.native_commands = 0
        #: Number of raster strips received.
        self.raster_strips = 0

    # -- transport interface -------------------------------------------- #

    async def scan(self, timeout: float = 10.0) -> list[dict]:
        """There is nothing to discover."""
        return []

    async def connect(self, address: str = "preview") -> None:
        """Mark the transport connected again (``address`` is ignored)."""
        self._connected = True

    async def disconnect(self) -> None:
        """Mark the transport disconnected; what was recorded stays available."""
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether writes are accepted."""
        return self._connected

    @property
    def has_notify(self) -> bool:
        """Always ``False``: nothing answers a status query."""
        return False

    def clear_notify_buffer(self) -> None:
        """No-op; there is no notify buffer."""

    async def read_notify(self, timeout: float) -> bytes:
        """Return no data, immediately."""
        return b""

    async def read_gatt(self, uuid: str) -> bytes:
        """There are no GATT characteristics to read."""
        raise RuntimeError("the preview transport has no GATT services")

    async def write(self, data: bytes) -> None:
        """Record bytes the facade would send over BLE.

        :raises RuntimeError: When the transport is disconnected.
        """
        self._require_connected()
        if data == _ESC_INIT:
            return
        if data.startswith(_GS_V_0):
            self._add_raster(data)
        elif len(data) == 3 and data.startswith(_ESC_FEED):
            self._parts.append(data[2] * self.FEED_LINE_PX)
        else:
            label = _describe_native(data)
            if label is not None:               # settings (code page, density, …) print nothing
                self.native_commands += 1
                self._parts.append(label)

    async def write_raster_strip(self, data: bytes, rows: int = 24) -> None:
        """Record one ``GS v 0`` strip (``rows`` is only used for pacing on a real printer).

        :raises RuntimeError: When the transport is disconnected.
        :raises ValueError: When ``data`` is not a complete raster payload.
        """
        self._require_connected()
        self._add_raster(data)

    # -- results --------------------------------------------------------- #

    @property
    def height(self) -> int:
        """Height in pixels of the rendered preview (at least 1)."""
        total = 0
        for part in self._parts:
            if isinstance(part, str):
                total += self.NOTE_HEIGHT_PX
            elif isinstance(part, int):
                total += part
            else:
                total += part.height
        return max(1, total)

    def image(self) -> "Image.Image":
        """Render everything recorded so far as one mode-``"1"`` image.

        The width is the print head width; a job without any output gives a
        blank one-pixel-high image.
        """
        from PIL import Image

        pieces: list[Image.Image] = []
        for part in self._parts:
            if isinstance(part, str):
                pieces.append(self._note_band(part))
            elif isinstance(part, int):
                if part > 0:
                    pieces.append(Image.new("1", (PAPER_WIDTH_PX, part), 1))
            else:
                pieces.append(part)
        if not pieces:
            return Image.new("1", (PAPER_WIDTH_PX, 1), 1)

        width = max(PAPER_WIDTH_PX, *(piece.width for piece in pieces))
        canvas = Image.new("1", (width, sum(piece.height for piece in pieces)), 1)
        y = 0
        for piece in pieces:
            canvas.paste(piece, (0, y))
            y += piece.height
        return canvas

    def png_bytes(self) -> bytes:
        """The preview as PNG data."""
        buffer = io.BytesIO()
        self.image().save(buffer, format="PNG")
        return buffer.getvalue()

    def save(self, path: "str | PathLike[str]") -> None:
        """Write the preview to ``path`` as a PNG file."""
        self.image().save(path, format="PNG")

    def summary(self) -> str:
        """One line telling what the preview contains and what it cannot show."""
        height = self.height
        text = (
            f"{PAPER_WIDTH_PX}x{height} px (about {height / 8:.0f} mm of paper), "
            f"{self.raster_strips} raster strip(s)"
        )
        if self.native_commands:
            text += (
                f"; {self.native_commands} native ESC/POS command(s) cannot be "
                "rendered and are shown as dashed notes"
            )
        return text

    # -- internals ------------------------------------------------------- #

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Preview transport is not connected.")

    def _add_raster(self, data: bytes) -> None:
        self._parts.append(raster_to_image(data))
        self.raster_strips += 1

    def _note_band(self, text: str) -> "Image.Image":
        """A dashed band with ``text`` standing in for an unrenderable command."""
        from PIL import Image, ImageDraw, ImageFont

        height = self.NOTE_HEIGHT_PX
        band = Image.new("1", (PAPER_WIDTH_PX, height), 1)
        draw = ImageDraw.Draw(band)
        for x in range(0, PAPER_WIDTH_PX, 4):
            draw.line([(x, 0), (x + 1, 0)], fill=0)
            draw.line([(x, height - 1), (x + 1, height - 1)], fill=0)
        try:
            font = ImageFont.load_default(size=11)
        except TypeError:                                  # Pillow < 10.1 has no size argument
            font = ImageFont.load_default()
        draw.text((4, 3), f"native: {text}", font=font, fill=0)
        return band
