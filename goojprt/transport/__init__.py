"""I/O transports for the GoojPrt PT-210.

Two independent transports are provided without a common abstract base
class. BLE is inherently asynchronous (via :mod:`bleak`) while SPP is
inherently synchronous (via :mod:`socket`); forcing a single interface
on top of both would produce a leaky abstraction. The
:class:`~goojprt.printer.GoojPrtPT210` facade keeps a reference to each
transport and dispatches calls to whichever one the caller has
activated.

* :class:`BleTransport` — asynchronous BLE transport; implements MTU
  chunking, pacing between chunks, and post-raster throttling.
* :class:`SppTransport` — thin RFCOMM socket wrapper; Linux only.
"""

from goojprt.transport.ble import BLEAK_AVAILABLE, BleTransport
from goojprt.transport.spp import SppTransport

__all__ = ["BleTransport", "SppTransport", "BLEAK_AVAILABLE"]
