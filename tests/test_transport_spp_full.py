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
