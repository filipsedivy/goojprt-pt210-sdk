"""Decoders for ESC/POS real-time status bytes (``DLE EOT n``).

Pure and I/O-free like :mod:`goojprt.commands`. The bit layouts follow the
Epson ESC/POS reference; they have not been verified against PT-210
firmware, which may report fewer flags (or none at all over BLE).

Each request ``n`` answers with one byte:

===  ================  ==========================================================
n    Request           Flags
===  ================  ==========================================================
1    printer           ``offline``
2    offline cause     ``cover_open``, ``feed_button``, ``paper_end``, ``error``
3    error cause       ``cutter_error``, ``unrecoverable_error``,
                       ``recoverable_error``
4    paper sensor      ``paper_low`` (bits 2–3), ``paper_end`` (bits 5–6)
===  ================  ==========================================================
"""

PRINTER = 1
OFFLINE_CAUSE = 2
ERROR_CAUSE = 3
PAPER_SENSOR = 4

#: Request number → flag name → bit mask inside the response byte.
_FLAGS: dict[int, dict[str, int]] = {
    PRINTER: {"offline": 0x08},
    OFFLINE_CAUSE: {
        "cover_open": 0x04,
        "feed_button": 0x08,
        "paper_end": 0x20,
        "error": 0x40,
    },
    ERROR_CAUSE: {
        "cutter_error": 0x08,
        "unrecoverable_error": 0x20,
        "recoverable_error": 0x40,
    },
    PAPER_SENSOR: {"paper_low": 0x0C, "paper_end": 0x60},
}

#: Flags that mean the printer needs attention. ``feed_button`` is left out
#: on purpose: some firmware keeps that bit permanently set.
_FAULT_FLAGS: dict[int, frozenset[str]] = {
    PRINTER: frozenset({"offline"}),
    OFFLINE_CAUSE: frozenset({"cover_open", "paper_end", "error"}),
    ERROR_CAUSE: frozenset(_FLAGS[ERROR_CAUSE]),
    PAPER_SENSOR: frozenset({"paper_low", "paper_end"}),
}


def decode_status(n: int, byte: int) -> dict[str, bool]:
    """Split a ``DLE EOT n`` response byte into named flags.

    :param n: The request number the byte answers (1–4).
    :param byte: The response byte.
    :returns: ``{flag name: is set}`` for every flag defined for ``n``.
    :raises ValueError: When ``n`` is not 1–4.
    """
    try:
        masks = _FLAGS[n]
    except KeyError:
        raise ValueError(f"unknown DLE EOT request {n!r}; expected 1-4") from None
    return {name: bool(byte & mask) for name, mask in masks.items()}


def status_ok(n: int, byte: int) -> bool:
    """Whether a ``DLE EOT n`` response byte reports no fault.

    :raises ValueError: When ``n`` is not 1–4.
    """
    flags = decode_status(n, byte)
    return not any(flags[name] for name in _FAULT_FLAGS[n])
