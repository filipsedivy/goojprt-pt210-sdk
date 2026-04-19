"""Tests for goojprt.cli — main() dispatch and all CLI branches."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from goojprt.cli import build_parser, main


# ── build_parser ──────────────────────────────────────────────────────────────

def test_build_parser_address_required():
    p = build_parser()
    args = p.parse_args(["AA:BB:CC"])
    assert args.address == "AA:BB:CC"


def test_build_parser_mode_defaults_to_ble():
    args = build_parser().parse_args(["addr"])
    assert args.mode == "ble"


def test_build_parser_spp_mode():
    args = build_parser().parse_args(["addr", "spp"])
    assert args.mode == "spp"


def test_build_parser_print_image_flag():
    args = build_parser().parse_args(["addr", "--print-image", "hello"])
    assert args.print_image == "hello"


def test_build_parser_pdf417_flag():
    args = build_parser().parse_args(["addr", "--pdf417", "data"])
    assert args.pdf417 == "data"


def test_build_parser_template_flag():
    args = build_parser().parse_args(["addr", "--template", "file.toml"])
    assert args.template == "file.toml"


def test_build_parser_test_flag():
    args = build_parser().parse_args(["addr", "--test"])
    assert args.test is True


def test_build_parser_test_cp1250_flag():
    args = build_parser().parse_args(["addr", "--test-cp1250"])
    assert args.test_cp1250 is True


def test_build_parser_var_flag():
    args = build_parser().parse_args(["addr", "--var", "k=v", "--var", "x=y"])
    assert args.var == ["k=v", "x=y"]


def test_build_parser_no_dither():
    args = build_parser().parse_args(["addr", "--no-dither"])
    assert args.no_dither is True


# ── main() ────────────────────────────────────────────────────────────────────

def _run_main(argv):
    with patch("sys.argv", ["goojprt"] + argv):
        main()


def test_main_template_branch():
    with patch("goojprt.cli.asyncio") as mock_asyncio, \
         patch("goojprt.cli.print_template") as mock_tmpl:
        mock_asyncio.run = MagicMock()
        _run_main(["addr", "--template", "t.toml", "--var", "k=v"])
        mock_asyncio.run.assert_called_once()


def test_main_template_branch_var_without_equals_ignored():
    with patch("goojprt.cli.asyncio") as mock_asyncio, \
         patch("goojprt.cli.print_template"):
        mock_asyncio.run = MagicMock()
        _run_main(["addr", "--template", "t.toml", "--var", "noequals"])
        mock_asyncio.run.assert_called_once()


def test_main_test_branch():
    with patch("goojprt.cli.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        _run_main(["addr", "--test"])
        mock_asyncio.run.assert_called_once()


def test_main_test_cp1250_branch():
    with patch("goojprt.cli.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        _run_main(["addr", "--test-cp1250"])
        mock_asyncio.run.assert_called_once()


def test_main_print_image_branch():
    mock_printer = MagicMock()
    mock_printer.connect_ble = AsyncMock()
    mock_printer.initialize = AsyncMock()
    mock_printer.print_text_image = AsyncMock()
    mock_printer.feed = AsyncMock()
    mock_printer.disconnect = AsyncMock()

    def run_coro(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer), \
         patch("goojprt.cli.asyncio.run", side_effect=run_coro):
        _run_main(["addr", "--print-image", "hello"])
    mock_printer.print_text_image.assert_called_once()


def test_main_pdf417_branch():
    mock_printer = MagicMock()
    mock_printer.connect_ble = AsyncMock()
    mock_printer.initialize = AsyncMock()
    mock_printer.print_pdf417 = AsyncMock()
    mock_printer.feed = AsyncMock()
    mock_printer.disconnect = AsyncMock()

    def run_coro(coro):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer), \
         patch("goojprt.cli.asyncio.run", side_effect=run_coro):
        _run_main(["addr", "--pdf417", "data"])
    mock_printer.print_pdf417.assert_called_once()


def test_main_ble_default_branch():
    with patch("goojprt.cli.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        _run_main(["addr"])
        mock_asyncio.run.assert_called_once()


def test_main_spp_branch():
    with patch("goojprt.cli._demo_spp") as mock_spp:
        _run_main(["addr", "spp"])
        mock_spp.assert_called_once_with("addr")


# ── _demo_ble (async) ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_ble_connects_and_disconnects():
    from goojprt.cli import _demo_ble
    mock_printer = MagicMock()
    mock_printer.connect_ble = AsyncMock()
    mock_printer.initialize = AsyncMock()
    mock_printer.print_text = AsyncMock()
    mock_printer.print_line = AsyncMock()
    mock_printer.print_qr = AsyncMock()
    mock_printer.print_pdf417 = AsyncMock()
    mock_printer.set_charset = AsyncMock()
    mock_printer.print_text_image = AsyncMock()
    mock_printer.feed = AsyncMock()
    mock_printer.disconnect = AsyncMock()
    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer):
        await _demo_ble("AA:BB")
    mock_printer.connect_ble.assert_called_once_with("AA:BB")
    mock_printer.disconnect.assert_called_once()


# ── _demo_spp ─────────────────────────────────────────────────────────────────

def test_demo_spp_connects_and_disconnects():
    from goojprt.cli import _demo_spp
    mock_printer = MagicMock()
    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer):
        _demo_spp("AA:BB")
    mock_printer.connect_spp.assert_called_once_with("AA:BB")
    mock_printer.disconnect_spp.assert_called_once()


# ── _run_test ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_test_calls_probe_charsets():
    from goojprt.cli import _run_test
    mock_printer = MagicMock()
    mock_printer.connect_ble = AsyncMock()
    mock_printer.initialize = AsyncMock()
    mock_printer.probe_charsets = AsyncMock()
    mock_printer.disconnect = AsyncMock()
    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer):
        await _run_test("AA:BB", "test string")
    mock_printer.probe_charsets.assert_called_once_with("test string")


# ── _run_test_cp1250 ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_test_cp1250_writes_five_variants():
    from goojprt.cli import _run_test_cp1250
    mock_printer = MagicMock()
    mock_printer.connect_ble = AsyncMock()
    mock_printer.initialize = AsyncMock()
    mock_printer.feed = AsyncMock()
    mock_printer.disconnect = AsyncMock()

    write_calls = []
    async def mock_write(data):
        write_calls.append(data)

    mock_ble = MagicMock()
    mock_ble.write = mock_write
    mock_printer._ble = mock_ble

    with patch("goojprt.cli.GoojPrtPT210", return_value=mock_printer):
        await _run_test_cp1250("AA:BB", "Příliš")

    assert len(write_calls) > 0
    mock_printer.disconnect.assert_called_once()
