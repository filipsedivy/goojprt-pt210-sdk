"""Tests for uncovered paths in goojprt.transport.spp.SppTransport."""
from unittest.mock import MagicMock, patch

import pytest

from goojprt.transport.spp import SppTransport


def _connected() -> SppTransport:
    t = SppTransport()
    t._sock = MagicMock()
    return t


def test_connect_raises_on_platform_without_af_bluetooth():
    with patch("goojprt.transport.spp.hasattr", return_value=False):
        t = SppTransport()
        with pytest.raises(OSError, match="macOS"):
            t.connect("AA:BB:CC:DD:EE:FF")


def test_disconnect_closes_socket():
    t = _connected()
    sock = t._sock  # save ref before disconnect clears it
    t.disconnect()
    sock.close.assert_called_once()
    assert t._sock is None


def test_disconnect_when_no_socket_is_noop():
    t = SppTransport()
    t.disconnect()  # should not raise


def test_is_connected_true_when_socket_present():
    assert _connected().is_connected is True


def test_is_connected_false_when_no_socket():
    assert SppTransport().is_connected is False


def test_write_raises_when_not_connected():
    t = SppTransport()
    with pytest.raises(RuntimeError, match="not connected"):
        t.write(b"hello")


def test_write_calls_sendall():
    t = _connected()
    t.write(b"hello")
    t._sock.sendall.assert_called_once_with(b"hello")


def test_connect_success_on_linux():
    import socket as socket_mod
    mock_sock = MagicMock()
    with patch("goojprt.transport.spp.hasattr", return_value=True), \
         patch("goojprt.transport.spp.socket") as mock_socket:
        mock_socket.socket.return_value = mock_sock
        mock_socket.AF_BLUETOOTH = 31
        mock_socket.SOCK_STREAM = 1
        mock_socket.BTPROTO_RFCOMM = 3
        t = SppTransport()
        t.connect("AA:BB:CC:DD:EE:FF", port=1)
    mock_sock.connect.assert_called_once_with(("AA:BB:CC:DD:EE:FF", 1))
