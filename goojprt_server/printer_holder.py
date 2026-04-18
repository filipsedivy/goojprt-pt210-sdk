"""Process-singleton accessor for the SDK printer instance.

The instance is created once in the lifespan startup and torn down at
shutdown. Routes retrieve it via :func:`get_printer` (FastAPI dependency)
so tests can override the dependency to inject a ``FakePrinter``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from goojprt import GoojPrtPT210

_printer: "GoojPrtPT210 | None" = None


def set_printer(p: "GoojPrtPT210 | None") -> None:
    global _printer
    _printer = p


def get_printer() -> "GoojPrtPT210":
    if _printer is None:
        raise RuntimeError("printer not initialised — startup did not complete")
    return _printer
