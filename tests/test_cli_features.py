"""CLI: --scan, --print-file, --preview, --density and the GOOJPRT_ADDRESS fallback."""
import argparse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt import cli
from goojprt.cli import ADDRESS_ENV, _connected, _resolve_target, build_parser, main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(ADDRESS_ENV, raising=False)


@pytest.fixture
def no_bluetooth():
    """Anything that tries to use a real transport fails the test."""
    with patch("goojprt.printer.BleTransport", side_effect=AssertionError("BLE was used")), \
         patch("goojprt.printer.SppTransport", side_effect=AssertionError("SPP was used")):
        yield


def _run(*argv: str) -> None:
    with patch("sys.argv", ["goojprt", *argv]):
        main()


def _png(path: Path, size, color=(0, 0, 0)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


# ── parser ────────────────────────────────────────────────────────────────────

class TestParser:
    def test_address_is_optional(self):
        args = build_parser().parse_args([])
        assert args.address is None and args.mode == "ble"

    def test_new_flags_and_defaults(self):
        args = build_parser().parse_args(["--scan", "--scan-all", "--scan-timeout", "2.5"])
        assert (args.scan, args.scan_all, args.scan_timeout) == (True, True, 2.5)
        args = build_parser().parse_args(["a", "--print-file", "x.png", "--fit", "width",
                                          "--scale", "0.5", "--preview", "o.png"])
        assert (args.print_file, args.fit, args.scale, args.preview) == ("x.png", "width", 0.5, "o.png")
        assert build_parser().parse_args(["a"]).fit == "shrink"

    @pytest.mark.parametrize("value, expected", [("dark", "dark"), ("light", "light"),
                                                 ("100", 100), ("0", 0), ("255", 255)])
    def test_density_accepts_presets_and_numbers(self, value, expected):
        assert build_parser().parse_args(["a", "--density", value]).density == expected

    @pytest.mark.parametrize("value", ["darkest", "256", "-1", "1.5", ""])
    def test_density_rejects_bad_values(self, value, capsys):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["a", "--density", value])
        assert exc.value.code == 2
        assert "density" in capsys.readouterr().err

    def test_fit_rejects_unknown_modes(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["a", "--fit", "stretch"])

    def test_help_mentions_the_new_commands(self, capsys):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--scan" in out and "--print-file" in out and "--preview" in out and ADDRESS_ENV in out


# ── address resolution ────────────────────────────────────────────────────────

class TestResolveTarget:
    @staticmethod
    def _args(address=None, mode="ble"):
        return argparse.Namespace(address=address, mode=mode)

    def test_explicit_address_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "FROM-ENV")
        assert _resolve_target(self._args("AA:BB")) == ("AA:BB", "ble")

    def test_environment_fills_in_a_missing_address(self, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "FROM-ENV")
        assert _resolve_target(self._args()) == ("FROM-ENV", "ble")

    def test_no_address_anywhere(self):
        assert _resolve_target(self._args()) == (None, "ble")

    def test_empty_environment_variable_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "")
        assert _resolve_target(self._args()) == (None, "ble")

    @pytest.mark.parametrize("word", ["spp", "ble"])
    def test_a_lone_transport_name_is_not_taken_as_the_address(self, word, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "FROM-ENV")
        assert _resolve_target(self._args(word)) == ("FROM-ENV", word)

    def test_a_lone_transport_name_without_environment(self):
        assert _resolve_target(self._args("spp")) == (None, "spp")

    def test_address_followed_by_a_transport_name(self):
        assert _resolve_target(self._args("AA:BB", "spp")) == ("AA:BB", "spp")


# ── main(): validation ────────────────────────────────────────────────────────

class TestMainValidation:
    def test_missing_address_is_a_usage_error_with_hints(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("--print-image", "x")
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert ADDRESS_ENV in err and "--scan" in err

    def test_address_from_the_environment_is_enough(self, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "FROM-ENV")
        with patch("goojprt.cli.asyncio") as fake_asyncio, \
             patch("goojprt.cli._demo_ble", new=MagicMock()) as demo:   # asyncio is faked: no coroutine
            fake_asyncio.run = MagicMock()
            _run()
        demo.assert_called_once_with("FROM-ENV")
        fake_asyncio.run.assert_called_once()

    def test_spp_with_the_address_from_the_environment(self, monkeypatch):
        monkeypatch.setenv(ADDRESS_ENV, "FROM-ENV")
        with patch("goojprt.cli._demo_spp") as demo:
            _run("spp")
        demo.assert_called_once_with("FROM-ENV")

    @pytest.mark.parametrize("flag", [["--preview", "o.png"], ["--density", "dark"]])
    def test_output_options_need_a_command_that_prints_bitmaps(self, flag, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("AA:BB", *flag)
        assert exc.value.code == 2
        assert "works with --template" in capsys.readouterr().err

    def test_preview_cannot_be_combined_with_spp(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("AA:BB", "spp", "--print-image", "x", "--preview", "o.png")
        assert exc.value.code == 2
        assert "spp" in capsys.readouterr().err

    def test_scan_needs_no_address(self):
        with patch("goojprt.cli._scan", new=AsyncMock()) as scan:
            _run("--scan", "--scan-timeout", "1.5")
        scan.assert_awaited_once_with(1.5, False)

    def test_preview_needs_no_address_for_a_template(self):
        with patch("goojprt.cli.print_template", new=AsyncMock()) as template:
            _run("--template", "t.toml", "--preview", "o.png")
        template.assert_awaited_once_with(None, "t.toml", None, density=None, preview="o.png")

    def test_density_reaches_the_template(self):
        with patch("goojprt.cli.print_template", new=AsyncMock()) as template:
            _run("AA:BB", "--template", "t.toml", "--density", "100")
        assert template.await_args.kwargs == {"density": 100, "preview": None}


# ── --scan ────────────────────────────────────────────────────────────────────

class TestScan:
    @staticmethod
    def _printer(devices=None, error=None):
        printer = MagicMock()
        printer.scan_ble = AsyncMock(return_value=devices, side_effect=error)
        return printer

    @pytest.mark.asyncio
    async def test_lists_named_devices_sorted_and_hides_unnamed_ones(self, capsys):
        devices = [{"name": "zeta", "address": "Z"}, {"name": "?", "address": "HIDDEN"},
                   {"name": "PT-210", "address": "AA:BB:CC"}]
        with patch("goojprt.cli.GoojPrtPT210", return_value=self._printer(devices)):
            await cli._scan(5.0, show_all=False)
        out = capsys.readouterr().out
        assert out.index("PT-210") < out.index("zeta")
        assert "AA:BB:CC" in out and "HIDDEN" not in out
        assert ADDRESS_ENV in out

    @pytest.mark.asyncio
    async def test_scan_all_includes_unnamed_devices(self, capsys):
        devices = [{"name": "?", "address": "UNNAMED"}]
        with patch("goojprt.cli.GoojPrtPT210", return_value=self._printer(devices)):
            await cli._scan(5.0, show_all=True)
        assert "UNNAMED" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_nothing_found_says_so(self, capsys):
        with patch("goojprt.cli.GoojPrtPT210", return_value=self._printer([])):
            await cli._scan(1.0, show_all=False)
        out = capsys.readouterr().out
        assert "No Bluetooth LE devices" in out and "--scan-all" in out

    @pytest.mark.asyncio
    async def test_a_failing_scan_is_a_one_line_error(self):
        with patch("goojprt.cli.GoojPrtPT210", return_value=self._printer(error=OSError("Bluetooth is off"))):
            with pytest.raises(SystemExit, match="scan failed: Bluetooth is off"):
                await cli._scan(1.0, show_all=False)

    @pytest.mark.asyncio
    async def test_scan_passes_the_timeout_on(self):
        printer = self._printer([])
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            await cli._scan(2.5, show_all=False)
        printer.scan_ble.assert_awaited_once_with(timeout=2.5)


# ── _connected ────────────────────────────────────────────────────────────────

class TestConnected:
    @pytest.mark.asyncio
    async def test_density_is_applied_right_after_initialisation(self):
        order: list[str] = []
        printer = MagicMock()
        printer.connect_ble = AsyncMock(side_effect=lambda *a: order.append("connect"))
        printer.initialize = AsyncMock(side_effect=lambda: order.append("initialize"))
        printer.set_density = AsyncMock(side_effect=lambda *a: order.append("density"))
        printer.disconnect = AsyncMock(side_effect=lambda: order.append("disconnect"))
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            async with _connected("AA:BB", density="dark"):
                order.append("work")
        assert order == ["connect", "initialize", "density", "work", "disconnect"]
        printer.set_density.assert_awaited_once_with("dark")

    @pytest.mark.asyncio
    async def test_no_density_leaves_the_printer_alone(self):
        printer = MagicMock()
        for name in ("connect_ble", "initialize", "disconnect", "set_density"):
            setattr(printer, name, AsyncMock())
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            async with _connected("AA:BB"):
                pass
        printer.set_density.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_writes_the_png_without_touching_bluetooth(self, tmp_path, no_bluetooth, capsys):
        out = tmp_path / "o.png"
        async with _connected(None, preview=str(out)) as printer:
            await printer.print_text_image("Příliš")
        with Image.open(out) as png:
            assert png.width == 384
        assert "Preview saved" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_preview_writes_nothing_when_the_work_fails(self, tmp_path, no_bluetooth):
        out = tmp_path / "o.png"
        with pytest.raises(RuntimeError, match="boom"):
            async with _connected(None, preview=str(out)):
                raise RuntimeError("boom")
        assert not out.exists()


# ── end to end through main(), without mocks ─────────────────────────────────

@pytest.mark.usefixtures("no_bluetooth")
class TestEndToEnd:
    def test_print_file_scales_a_wide_image_down_and_feeds(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-file", str(_png(tmp_path / "big.png", (1000, 500))), "--preview", str(out))
        with Image.open(out) as png:
            assert png.size == (384, 192 + 3 * 30)         # 500*384/1000, then feed(3)
            assert png.convert("L").crop((0, 0, 384, 192)).getextrema()[1] == 0   # all black photo

    def test_fit_width_enlarges_a_small_image(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-file", str(_png(tmp_path / "s.png", (100, 50))), "--fit", "width",
             "--preview", str(out))
        with Image.open(out) as png:
            assert png.height == 192 + 90

    def test_scale_and_align_apply(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-file", str(_png(tmp_path / "s.png", (100, 50))), "--fit", "width",
             "--scale", "0.5", "--align", "right", "--preview", str(out))
        with Image.open(out) as png:
            row = png.convert("L").crop((0, 0, 384, 96))
            black = [x for x in range(384) if row.getpixel((x, 40)) == 0]
        assert min(black) == 192 and max(black) == 383

    def test_unreadable_file_fails_before_any_connection(self, tmp_path):
        (tmp_path / "bad.png").write_text("not an image")
        with patch("goojprt.cli.GoojPrtPT210") as facade:
            with pytest.raises(SystemExit, match="cannot use"):
                _run("AA:BB", "--print-file", str(tmp_path / "bad.png"))
        facade.assert_not_called()

    def test_missing_file_fails_before_any_connection(self):
        with patch("goojprt.cli.GoojPrtPT210") as facade:
            with pytest.raises(SystemExit, match="cannot use"):
                _run("AA:BB", "--print-file", "/no/such/file.png")
        facade.assert_not_called()

    def test_print_image_text_preview(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-image", "Příliš žluťoučký kůň", "--preview", str(out))
        assert out.exists()

    def test_pdf417_preview(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--pdf417", "GoojPrt-PT210", "--preview", str(out))
        with Image.open(out) as png:
            assert png.width == 384 and png.height > 30

    def test_template_preview_with_variables(self, tmp_path, capsys):
        out = tmp_path / "o.png"
        _run("--template", str(EXAMPLES / "receipt.toml"), "--var", "shop=Corner",
             "--var", "total=1.00", "--preview", str(out))
        assert out.exists()
        assert "Preview saved" in capsys.readouterr().out

    def test_template_error_is_a_one_line_message(self, tmp_path):
        template = tmp_path / "t.toml"
        template.write_text('[[items]]\ntype = "image"\npath = "missing.png"\n', encoding="utf-8")
        with pytest.raises(SystemExit, match=r"goojprt: item 1 \(image\)"):
            _run("--template", str(template), "--preview", str(tmp_path / "o.png"))

    def test_density_is_accepted_together_with_preview(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-image", "x", "--density", "dark", "--preview", str(out))
        assert out.exists()
