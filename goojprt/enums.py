"""Enumerations for ESC/POS parameters used across the SDK.

These ``IntEnum`` types are intentionally thin wrappers around the raw
values expected by the printer firmware, so they can be used directly as
byte arguments to ESC/POS commands without explicit conversion.
"""

from enum import IntEnum


class Align(IntEnum):
    """Horizontal text / object alignment.

    Used as the ``n`` parameter of the ``ESC a n`` command.
    """

    LEFT = 0
    CENTER = 1
    RIGHT = 2


class TextSize(IntEnum):
    """Character size multiplier, encoded as a bit mask for ``GS ! n``.

    The high nibble encodes the horizontal multiplier and the low nibble
    encodes the vertical multiplier (``0`` = 1×, ``1`` = 2×, ``2`` = 3×, …),
    as defined by the Epson ESC/POS reference.

    .. versionchanged:: unreleased
        ``DOUBLE_HEIGHT``, ``DOUBLE_WIDTH`` and ``DOUBLE_BOTH`` now do what
        their names say. Earlier releases shipped ``0x11`` (2× wide *and*
        2× tall), ``0x20`` (3× wide) and ``0x31`` (4× wide, 2× tall).
    """

    NORMAL = 0x00
    DOUBLE_HEIGHT = 0x01
    DOUBLE_WIDTH = 0x10
    DOUBLE_BOTH = 0x11


class CodePage(IntEnum):
    """ESC/POS character code table, selectable via ``ESC t n``.

    Most low-cost Chinese thermal printers ship with only a minimal subset
    of code pages. If guaranteed diacritic support is required, render the
    text as a bitmap (see ``rendering.text.render_text_image``) instead of
    switching the firmware code page.
    """

    PC437 = 0       # USA / Standard Europe (factory default on most units)
    PC850 = 2       # Multilingual Latin-1
    PC852 = 18      # Latin-2, includes Czech diacritics (if firmware supports it)
    WPC1250 = 16    # Windows Central European, includes Czech diacritics
    PC866 = 17      # Cyrillic
    PC858 = 19      # Multilingual Latin-1 with Euro sign
    #: Windows-1250 at the slot the common ESC/POS tables use for it
    #: (escpos-printer-db). Slot 16 above is Windows-1252 in those tables, so
    #: which of the two really is CP1250 depends on the firmware — run
    #: ``goojprt <addr> --test`` to find out.
    WPC1250_STD = 45
