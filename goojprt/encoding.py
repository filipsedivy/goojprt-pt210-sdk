"""Text encoding helpers and cross-platform font discovery.

This module is the bridge between Python ``str`` objects and the byte
streams that ESC/POS commands expect, plus a tiny utility for locating
a usable truetype font on the host system without relying on
system-specific APIs.

Exports:
    - ``CODEPAGE_TO_ENCODING``: map from :class:`~goojprt.enums.CodePage`
      to the name of the matching Python codec.
    - :func:`text_to_bytes`: encode a string with a graceful UTF-8 fallback.
    - :func:`find_system_font`: return the first existing font path from
      :data:`~goojprt.constants.FONT_CANDIDATES`.
"""

from pathlib import Path

from goojprt.constants import FONT_CANDIDATES
from goojprt.enums import CodePage


#: ESC/POS code page → Python codec name (as accepted by ``str.encode``).
CODEPAGE_TO_ENCODING: dict[int, str] = {
    CodePage.PC437:   "cp437",
    CodePage.PC850:   "cp850",
    CodePage.PC852:   "cp852",
    CodePage.WPC1250: "cp1250",
    CodePage.PC866:   "cp866",
    CodePage.PC858:   "cp858",
}


def text_to_bytes(text: str, encoding: str = "gb2312") -> bytes:
    """Encode ``text`` into bytes suitable for the printer's data stream.

    The PT-210 firmware usually expects GB2312/GBK (Chinese) for native text
    output, but plain ASCII also works with ``"ascii"`` or ``"utf-8"``. When
    the chosen codec cannot represent a character (``UnicodeEncodeError``)
    or is unknown to Python (``LookupError``) the function falls back to
    UTF-8 with ``errors="replace"`` so callers never receive an exception.

    :param text: Input string.
    :param encoding: Name of the Python codec to try first, e.g.
        ``"gb2312"``, ``"cp1250"`` or ``"ascii"``.
    :returns: Raw bytes for inclusion in an ESC/POS payload.
    """
    try:
        return text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return text.encode("utf-8", errors="replace")


def find_system_font() -> str | None:
    """Return the path to the first available fallback system font.

    Iterates :data:`~goojprt.constants.FONT_CANDIDATES` in order (macOS →
    Linux → Windows) and returns the first path that exists on disk.

    :returns: Absolute path to a usable ``.ttf``/``.ttc`` file, or ``None``
        when no candidate exists (in which case callers should fall back
        to :func:`PIL.ImageFont.load_default`).
    """
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None
