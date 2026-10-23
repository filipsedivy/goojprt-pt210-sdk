"""Connections are always closed, and a failing disconnect never hides the real error."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt import cli
from goojprt.printer import GoojPrtPT210, disconnect_quietly
from goojprt.template import print_template
from goojprt.transport.ble import BleTransport
from goojprt.transport.spp import SppTransport


class Boom(Exception):
    """The error the work inside a session raises."""


def _ble_transport(disconnect=None) -> MagicMock:
    t = MagicMock(spec=BleTransport)
    t.connect = AsyncMock()
    t.write = AsyncMock()
    t.disconnect = disconnect or AsyncMock()
    return t


def _mock_printer(**overrides) -> MagicMock:
    p = MagicMock()
    for name in ("connect_ble", "initialize", "disconnect", "print_text", "print_line",
                 "print_qr", "print_pdf417", "set_charset", "print_text_image", "feed",
                 "probe_charsets"):
        setattr(p, name, AsyncMock())
    for name, value in overrides.items():
        setattr(p, name, value)
    return p


# ── disconnect_quietly ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_quietly_swallows_and_logs_a_failure(caplog):
    printer = MagicMock()
    printer.disconnect = AsyncMock(side_effect=OSError("link lost"))
    with caplog.at_level(logging.WARNING, logger="goojprt.printer"):
        await disconnect_quietly(printer)       # must not raise
    assert "disconnecting the printer failed" in caplog.text


@pytest.mark.asyncio
async def test_disconnect_quietly_does_not_swallow_cancellation():
    printer = MagicMock()
    printer.disconnect = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await disconnect_quietly(printer)


# ── GoojPrtPT210.ble() ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ble_session_connects_initialises_and_disconnects():
    transport = _ble_transport()
    with patch("goojprt.printer.BleTransport", return_value=transport):
        async with GoojPrtPT210.ble("AA:BB") as printer:
            assert isinstance(printer, GoojPrtPT210)
            transport.connect.assert_awaited_once_with("AA:BB")
            transport.write.assert_awaited_once_with(b"\x1b\x40")      # ESC @
            transport.disconnect.assert_not_called()
    transport.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_ble_session_can_skip_initialisation():
    transport = _ble_transport()
    with patch("goojprt.printer.BleTransport", return_value=transport):
        async with GoojPrtPT210.ble("AA:BB", initialize=False):
            pass
    transport.write.assert_not_called()


@pytest.mark.asyncio
async def test_ble_session_forwards_connection_options():
    with patch("goojprt.printer.BleTransport", return_value=_ble_transport()) as factory:
        async with GoojPrtPT210.ble("AA:BB", chunk_size=100, chunk_delay=0.01, initialize=False):
            pass
    factory.assert_called_once_with(on_disconnect=None, chunk_size=100, chunk_delay=0.01)


@pytest.mark.asyncio
async def test_ble_session_disconnects_when_the_block_raises():
    transport = _ble_transport()
    with patch("goojprt.printer.BleTransport", return_value=transport):
        with pytest.raises(Boom):
            async with GoojPrtPT210.ble("AA:BB"):
                raise Boom
    transport.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_disconnect_does_not_replace_the_original_error():
    transport = _ble_transport(disconnect=AsyncMock(side_effect=OSError("link lost")))
    with patch("goojprt.printer.BleTransport", return_value=transport):
        with pytest.raises(Boom):
            async with GoojPrtPT210.ble("AA:BB"):
                raise Boom


@pytest.mark.asyncio
async def test_a_failing_disconnect_after_success_is_not_an_error():
    transport = _ble_transport(disconnect=AsyncMock(side_effect=OSError("link lost")))
    with patch("goojprt.printer.BleTransport", return_value=transport):
        async with GoojPrtPT210.ble("AA:BB"):
            pass


@pytest.mark.asyncio
async def test_a_failed_connect_propagates_and_needs_no_disconnect():
    transport = _ble_transport()
    transport.connect = AsyncMock(side_effect=RuntimeError("no such device"))
    with patch("goojprt.printer.BleTransport", return_value=transport):
        with pytest.raises(RuntimeError, match="no such device"):
            async with GoojPrtPT210.ble("AA:BB"):
                pytest.fail("the block must not run")
    transport.disconnect.assert_not_called()


# ── GoojPrtPT210.spp() ───────────────────────────────────────────────────────

def _spp_transport() -> MagicMock:
    t = MagicMock(spec=SppTransport)
    t.is_connected = True
    return t


def test_spp_session_connects_initialises_and_closes():
    transport = _spp_transport()
    with patch("goojprt.printer.SppTransport", return_value=transport):
        with GoojPrtPT210.spp("AA:BB", port=2) as printer:
            assert isinstance(printer, GoojPrtPT210)
            transport.connect.assert_called_once_with("AA:BB", 2)
            transport.write.assert_called_once_with(b"\x1b\x40")
            transport.disconnect.assert_not_called()
    transport.disconnect.assert_called_once()


def test_spp_session_closes_when_the_block_raises_even_if_closing_fails():
    transport = _spp_transport()
    transport.disconnect.side_effect = OSError("already closed")
    with patch("goojprt.printer.SppTransport", return_value=transport):
        with pytest.raises(Boom):
            with GoojPrtPT210.spp("AA:BB", initialize=False):
                raise Boom
    transport.disconnect.assert_called_once()


# ── CLI ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_ble_disconnects_when_printing_fails():
    printer = _mock_printer(print_qr=AsyncMock(side_effect=Boom))
    with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
        with pytest.raises(Boom):
            await cli._demo_ble("AA:BB")
    printer.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_command_disconnects_when_the_probe_fails():
    printer = _mock_printer(probe_charsets=AsyncMock(side_effect=Boom))
    with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
        with pytest.raises(Boom):
            await cli._run_test("AA:BB", "x")
    printer.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_cp1250_command_disconnects_when_writing_fails():
    printer = _mock_printer()
    printer._ble = MagicMock()
    printer._ble.write = AsyncMock(side_effect=Boom)
    with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
        with pytest.raises(Boom):
            await cli._run_test_cp1250("AA:BB", "x")
    printer.disconnect.assert_awaited_once()


def test_spp_demo_closes_the_socket_when_printing_fails():
    printer = MagicMock()
    printer.print_text_spp.side_effect = Boom
    with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
        with pytest.raises(Boom):
            cli._demo_spp("AA:BB")
    printer.disconnect_spp.assert_called_once()


def test_print_image_command_disconnects_when_printing_fails():
    printer = _mock_printer(print_text_image=AsyncMock(side_effect=Boom))

    def run(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    with patch("goojprt.cli.GoojPrtPT210", return_value=printer), \
         patch("goojprt.cli.asyncio.run", side_effect=run), \
         patch("sys.argv", ["goojprt", "AA:BB", "--print-image", "x"]):
        with pytest.raises(Boom):
            cli.main()
    printer.disconnect.assert_awaited_once()


# ── templates ─────────────────────────────────────────────────────────────────

async def _template(tmp_path, printer, toml='[[items]]\ntype = "text"\ntext = "x"\n'):
    path = tmp_path / "t.toml"
    path.write_text(toml, encoding="utf-8")
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", str(path))


@pytest.mark.asyncio
async def test_template_disconnects_when_an_item_fails(tmp_path):
    printer = _mock_printer(print_text=AsyncMock(side_effect=Boom))
    with pytest.raises(Boom):
        await _template(tmp_path, printer)
    printer.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_keeps_the_original_error_when_disconnect_fails_too(tmp_path):
    printer = _mock_printer(print_text=AsyncMock(side_effect=Boom),
                            disconnect=AsyncMock(side_effect=OSError("link lost")))
    with pytest.raises(Boom):
        await _template(tmp_path, printer)


@pytest.mark.asyncio
async def test_template_disconnects_after_success(tmp_path, capsys):
    printer = _mock_printer()
    await _template(tmp_path, printer)
    printer.disconnect.assert_awaited_once()
    assert "Done, disconnected." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_template_does_not_claim_success_when_it_failed(tmp_path, capsys):
    printer = _mock_printer(print_text=AsyncMock(side_effect=Boom))
    with pytest.raises(Boom):
        await _template(tmp_path, printer)
    assert "Done" not in capsys.readouterr().out
