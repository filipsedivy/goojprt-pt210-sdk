"""Classic Bluetooth Serial Port Profile (RFCOMM) transport.

Synchronous, Linux-only. macOS does not expose ``AF_BLUETOOTH`` through
the CPython ``socket`` module; BLE should be used there instead.
"""

import socket
from typing import Optional


class SppTransport:
    """Synchronous Bluetooth SPP / RFCOMM transport.

    Only supported on Linux. Attempts to :meth:`connect` on macOS raise
    :class:`OSError` with a hint to switch to BLE.
    """

    def __init__(self) -> None:
        """Create a disconnected transport; call :meth:`connect` to attach."""
        self._sock: Optional[socket.socket] = None

    def connect(self, address: str, port: int = 1) -> None:
        """Open an RFCOMM socket to the printer.

        :param address: Bluetooth MAC address of the printer.
        :param port: RFCOMM channel, usually ``1``.
        :raises OSError: On platforms without ``AF_BLUETOOTH`` support
            (notably macOS).
        """
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise OSError(
                "SPP / RFCOMM is not available on macOS via the Python socket module.\n"
                "Use the BLE transport instead (connect_ble(address))."
            )
        self._sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM  # type: ignore[attr-defined]
        )
        self._sock.connect((address, port))

    def disconnect(self) -> None:
        """Close the RFCOMM socket (if open)."""
        if self._sock:
            self._sock.close()
            self._sock = None

    @property
    def is_connected(self) -> bool:
        """Whether the RFCOMM socket is currently open."""
        return self._sock is not None

    def write(self, data: bytes) -> None:
        """Send raw bytes over the RFCOMM socket.

        :raises RuntimeError: When the transport is not connected.
        """
        if not self.is_connected:
            raise RuntimeError("SPP transport is not connected.")
        self._sock.sendall(data)
