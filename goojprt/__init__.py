"""Unofficial Python SDK for the GoojPrt PT-210 thermal printer.

The PT-210 is a low-cost 58 mm thermal receipt printer with a 48 mm
printable area (384 pixels at 203 DPI). This package provides an
ergonomic wrapper around the ESC/POS command set and both transports
the printer supports — Bluetooth Low Energy (BLE) and classic
Bluetooth Serial Port Profile (SPP).

Quick start (BLE, cross-platform)::

    import asyncio
    from goojprt import GoojPrtPT210, Align

    async def main() -> None:
        printer = GoojPrtPT210()
        await printer.connect_ble("XX:XX:XX:XX:XX:XX")
        await printer.initialize()
        await printer.print_text("Hello, world!", align=Align.CENTER, bold=True)
        await printer.feed(3)
        await printer.disconnect()

    asyncio.run(main())

For lower-level access, import the relevant submodule directly
(:mod:`goojprt.commands`, :mod:`goojprt.rendering`,
:mod:`goojprt.raster`, :mod:`goojprt.transport`, :mod:`goojprt.template`,
:mod:`goojprt.cli`).
"""

__version__ = "0.1.0"

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align, CodePage, TextSize
from goojprt.printer import GoojPrtPT210
from goojprt.template import print_template

# Backward-compatible alias kept for historical callers that imported
# `_print_template` from this module.
_print_template = print_template

__all__ = [
    "GoojPrtPT210",
    "Align",
    "TextSize",
    "CodePage",
    "PAPER_WIDTH_PX",
    "print_template",
    "_print_template",
    "__version__",
]
