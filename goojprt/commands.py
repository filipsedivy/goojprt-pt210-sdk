"""ESC/POS command builders for the GoojPrt PT-210.

Every function in this module is *pure*: it has no side effects, performs
no I/O, and merely returns the byte sequence that the caller sends over
the chosen transport (BLE or SPP).

Two levels of helpers are provided:

* **Low-level builders** (:func:`init`, :func:`align`, :func:`bold`,
  :func:`feed`, :func:`cut`, …) emit a single ESC/POS escape sequence.
* **Composite builders** (:func:`build_text_block`, :func:`build_qr_block`)
  concatenate several low-level commands into a ready-to-send block.
  These are shared by the BLE and SPP print APIs of
  :class:`~goojprt.printer.GoojPrtPT210` to avoid duplicating byte
  construction logic.

Reference: ``ESC/POS Command Reference`` by Epson. Only the subset
implemented by the PT-210 firmware is exposed here.
"""

from goojprt.encoding import text_to_bytes
from goojprt.enums import Align, CodePage, TextSize


def init() -> bytes:
    """``ESC @`` — initialise the printer (reset it to its default state)."""
    return b"\x1b\x40"


def align(a: Align) -> bytes:
    """``ESC a n`` — set horizontal alignment (LEFT / CENTER / RIGHT)."""
    return bytes([0x1B, 0x61, int(a)])


def text_size(s: TextSize) -> bytes:
    """``GS ! n`` — set character size (NORMAL / DOUBLE_HEIGHT / …)."""
    return bytes([0x1D, 0x21, int(s)])


def bold(enabled: bool) -> bytes:
    """``ESC E n`` — toggle emphasised (bold) printing."""
    return bytes([0x1B, 0x45, 0x01 if enabled else 0x00])


def underline(enabled: bool) -> bytes:
    """``ESC - n`` — toggle underline printing."""
    return bytes([0x1B, 0x2D, 0x01 if enabled else 0x00])


def feed(lines: int = 1) -> bytes:
    """``ESC d n`` — feed paper by ``lines`` rows (clamped to 0–255)."""
    return bytes([0x1B, 0x64, max(0, min(lines, 255))])


def line_spacing(dots: int = 30) -> bytes:
    """``ESC 3 n`` — set line spacing, measured in motion units (0–255)."""
    return bytes([0x1B, 0x33, max(0, min(dots, 255))])


def cut() -> bytes:
    """``GS V A`` — paper cut (no-op on PT-210, which lacks a cutter)."""
    return bytes([0x1D, 0x56, 0x41, 0x00])


def charset(cp: CodePage) -> bytes:
    """``ESC t n`` — select code page for native ESC/POS text output."""
    return bytes([0x1B, 0x74, int(cp)])


def energy(dots: int = 7, heating: int = 120, interval: int = 2) -> bytes:
    """``ESC 7 n1 n2 n3`` — configure thermal head heating parameters.

    :param dots: Maximum number of simultaneously heated dots, 0–7.
        Higher values print faster but draw more current.
    :param heating: Heating time, 0–255. Higher values produce darker
        output (the factory default is ≈ 80).
    :param interval: Heating interval, 0–255. Lower values print faster
        (the factory default is ≈ 2).
    """
    return bytes([0x1B, 0x37, dots & 0xFF, heating & 0xFF, interval & 0xFF])


def font(font_b: bool = False) -> bytes:
    """``ESC M n`` — select font. ``False`` = Font A (12×24), ``True`` = Font B (9×17)."""
    return bytes([0x1B, 0x4D, 0x01 if font_b else 0x00])


def barcode_qr(data: str, size: int = 6, error_correction: int = 1) -> bytes:
    r"""``GS ( k`` — build the four-command sequence that prints a QR code.

    The sequence configures the model/error-correction level, stores the
    payload into the printer's symbol buffer, and then triggers printing.

    :param data: Payload to encode (encoded as UTF-8 on the wire).
    :param size: Module size, 1–16 (default ``6``).
    :param error_correction: Correction level — ``0``\ =L, ``1``\ =M,
        ``2``\ =Q, ``3``\ =H (default ``1``).
    :returns: Bytes containing the complete QR command sequence.
    """
    encoded = data.encode("utf-8")
    length = len(encoded) + 3
    cmds = bytearray()
    # Select model (Model 2 = 0x32, required for size to take effect)
    cmds += bytes([0x1D, 0x28, 0x6B, 0x04, 0x00, 0x31, 0x41, 0x32, 0x00])
    # EC level
    cmds += bytes([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x45, error_correction + 48])
    # Module size
    cmds += bytes([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x43, size])
    # Store data
    cmds += bytes([0x1D, 0x28, 0x6B, length & 0xFF, (length >> 8) & 0xFF,
                   0x31, 0x50, 0x30])
    cmds += encoded
    # Print
    cmds += bytes([0x1D, 0x28, 0x6B, 0x03, 0x00, 0x31, 0x51, 0x30])
    return bytes(cmds)


def build_text_block(
    text: str,
    align_val: Align = Align.LEFT,
    bold_on: bool = False,
    underline_on: bool = False,
    size_val: TextSize = TextSize.NORMAL,
    newline: bool = True,
    encoding: str = "gb2312",
) -> bytes:
    """Build the full ESC/POS block that prints a single text line.

    The resulting byte stream contains, in order: alignment, bold toggle,
    underline toggle, text-size setting, the encoded text, and (optionally)
    a trailing line feed. This function is shared by BLE and SPP print
    APIs to keep the wire format identical.
    """
    data = bytearray()
    data += align(align_val)
    data += bold(bold_on)
    data += underline(underline_on)
    data += text_size(size_val)
    data += text_to_bytes(text, encoding)
    if newline:
        data += b"\n"
    return bytes(data)


def build_qr_block(
    data: str,
    size: int = 6,
    align_val: Align = Align.CENTER,
    error_correction: int = 1,
) -> bytes:
    """Build a QR block: alignment + QR command sequence + trailing newline.

    Shared by both the BLE and SPP QR APIs.
    """
    return align(align_val) + barcode_qr(data, size, error_correction) + b"\n"
