"""CLI: --print-text, --calibrate / --calibrate-pick and the --profile options."""
import builtins
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt import cli
from goojprt.cli import main
from goojprt.enums import Align, TextSize
from goojprt.profile import CANDIDATES, PROFILE_ENV, TextProfile, load_profile, save_profile

CZ = "Příliš žluťoučký kůň"


def _run(*argv: str) -> None:
    with patch("sys.argv", ["goojprt", *argv]):
        main()


@pytest.fixture
def profile_file(tmp_path) -> Path:
    file = tmp_path / "profile.toml"
    save_profile(TextProfile(18, "cp852"), file)
    return file


@pytest.fixture
def no_bluetooth():
    with patch("goojprt.printer.BleTransport", side_effect=AssertionError("BLE was used")):
        yield


def _mock_printer(**extra) -> MagicMock:
    printer = MagicMock()
    for name in ("connect_ble", "initialize", "disconnect", "print_text_auto", "feed",
                 "apply_profile", "print_charset_calibration"):
        setattr(printer, name, AsyncMock())
    for name, value in extra.items():
        setattr(printer, name, value)
    return printer


# ── --print-text ─────────────────────────────────────────────────────────────

class TestPrintText:
    @pytest.mark.usefixtures("no_bluetooth")
    def test_czech_goes_native_with_a_profile(self, tmp_path, profile_file, capsys):
        out = tmp_path / "o.png"
        _run("--print-text", CZ, "--profile", str(profile_file), "--preview", str(out))
        text = capsys.readouterr().out
        assert "Native text profile: ESC t 18, cp852" in text
        assert "1 native ESC/POS command(s)" in text          # one native line, no bitmap
        with Image.open(out) as png:
            assert png.height == 20 + 3 * 30                  # a note band plus feed(3)

    @pytest.mark.usefixtures("no_bluetooth")
    def test_without_a_profile_czech_is_rendered_as_a_bitmap(self, tmp_path, capsys):
        out = tmp_path / "o.png"
        _run("--print-text", CZ, "--no-profile", "--preview", str(out))
        text = capsys.readouterr().out
        assert "native ESC/POS" not in text and "Native text profile" not in text
        with Image.open(out) as png:
            assert png.height > 20 + 3 * 30

    @pytest.mark.usefixtures("no_bluetooth")
    def test_ascii_is_native_even_without_a_profile(self, tmp_path, capsys):
        _run("--print-text", "Hello", "--no-profile", "--preview", str(tmp_path / "o.png"))
        assert "1 native ESC/POS command(s)" in capsys.readouterr().out

    @pytest.mark.usefixtures("no_bluetooth")
    def test_a_line_the_page_cannot_show_becomes_a_bitmap(self, tmp_path, profile_file, capsys):
        _run("--print-text", "Cena\n5 €", "--profile", str(profile_file),
             "--preview", str(tmp_path / "o.png"))
        text = capsys.readouterr().out
        assert "1 native ESC/POS command(s)" in text and "raster strip(s)" in text

    def test_style_options_reach_the_printer(self, profile_file):
        printer = _mock_printer()
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            _run("AA:BB", "--print-text", "Hi", "--profile", str(profile_file), "--bold", "--underline",
                 "--size", "double_both", "--align", "center", "--font-size", "30")
        printer.print_text_auto.assert_awaited_once_with(
            "Hi", align=Align.CENTER, bold=True, underline=True,
            size=TextSize.DOUBLE_BOTH, font_size=30)
        printer.apply_profile.assert_awaited_once_with(TextProfile(18, "cp852"))
        printer.disconnect.assert_awaited_once()

    def test_it_needs_an_address_unless_previewing(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("--print-text", "x")
        assert exc.value.code == 2

    @pytest.mark.usefixtures("no_bluetooth")
    def test_preview_and_density_are_accepted(self, tmp_path):
        out = tmp_path / "o.png"
        _run("--print-text", "x", "--density", "dark", "--preview", str(out))
        assert out.exists()


# ── profile options ──────────────────────────────────────────────────────────

class TestProfileOptions:
    def test_a_missing_explicit_profile_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit, match="no native text profile at"):
            _run("AA:BB", "--print-text", "x", "--profile", str(tmp_path / "nope.toml"))

    def test_an_invalid_profile_is_a_one_line_error(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_text("[text]\ncode_page = 999\nencoding = \"cp852\"\n")
        with pytest.raises(SystemExit, match="goojprt: .*code_page"):
            _run("AA:BB", "--print-text", "x", "--profile", str(bad))

    def test_profile_and_no_profile_exclude_each_other(self, profile_file, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("AA:BB", "--print-text", "x", "--profile", str(profile_file), "--no-profile")
        assert exc.value.code == 2
        assert "exclude each other" in capsys.readouterr().err

    def test_the_default_location_is_used_when_no_option_is_given(self, monkeypatch, tmp_path):
        default = tmp_path / "default.toml"
        save_profile(TextProfile(45, "cp1250"), default)
        monkeypatch.setenv(PROFILE_ENV, str(default))
        printer = _mock_printer()
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            _run("AA:BB", "--print-text", "x")
        printer.apply_profile.assert_awaited_once_with(TextProfile(45, "cp1250"))

    def test_no_profile_ignores_a_saved_one(self, monkeypatch, profile_file):
        monkeypatch.setenv(PROFILE_ENV, str(profile_file))
        printer = _mock_printer()
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            _run("AA:BB", "--print-text", "x", "--no-profile")
        printer.apply_profile.assert_not_called()

    def test_a_broken_default_profile_does_not_block_commands_that_do_not_use_it(self, monkeypatch, tmp_path):
        broken = tmp_path / "broken.toml"
        broken.write_text("not toml [")
        monkeypatch.setenv(PROFILE_ENV, str(broken))
        printer = _mock_printer(print_pdf417=AsyncMock())
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer):
            _run("AA:BB", "--pdf417", "data")
        printer.print_pdf417.assert_awaited_once()

    def test_templates_receive_the_profile(self, profile_file):
        with patch("goojprt.cli.print_template", new=AsyncMock()) as template:
            _run("AA:BB", "--template", "t.toml", "--profile", str(profile_file))
        assert template.await_args.kwargs["profile"] == TextProfile(18, "cp852")

    def test_templates_get_no_profile_with_no_profile(self, profile_file, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV, str(profile_file))
        with patch("goojprt.cli.print_template", new=AsyncMock()) as template:
            _run("AA:BB", "--template", "t.toml", "--no-profile")
        assert template.await_args.kwargs["profile"] is None


# ── --calibrate ──────────────────────────────────────────────────────────────

def _sheet():
    return dict(zip("ABCDEFGH", CANDIDATES))


class TestCalibrate:
    def test_the_sheet_is_printed_without_any_profile_applied(self, monkeypatch, profile_file, capsys):
        monkeypatch.setenv(PROFILE_ENV, str(profile_file))
        printer = _mock_printer(print_charset_calibration=AsyncMock(return_value=_sheet()))
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer), \
             patch("sys.stdin.isatty", return_value=False):
            _run("AA:BB", "--calibrate")
        printer.print_charset_calibration.assert_awaited_once_with(cli.CZECH_TEST_TEXT)
        printer.apply_profile.assert_not_called()          # the sheet must show the raw printer
        printer.disconnect.assert_awaited_once()

    def test_non_interactive_runs_print_the_legend_and_save_nothing(self, tmp_path, capsys):
        target = tmp_path / "p.toml"
        printer = _mock_printer(print_charset_calibration=AsyncMock(return_value=_sheet()))
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer), \
             patch("sys.stdin.isatty", return_value=False):
            _run("AA:BB", "--calibrate", "--profile", str(target))
        out = capsys.readouterr().out
        assert "A: ESC t 18, cp852, FS ." in out and "H: ESC t 16, cp1250, default mode" in out
        assert "--calibrate-pick LETTER" in out
        assert not target.exists()

    def test_custom_text_reaches_the_printer(self):
        printer = _mock_printer(print_charset_calibration=AsyncMock(return_value=_sheet()))
        with patch("goojprt.cli.GoojPrtPT210", return_value=printer), \
             patch("sys.stdin.isatty", return_value=False):
            _run("AA:BB", "--calibrate", "--calibrate-text", "žluťoučký")
        printer.print_charset_calibration.assert_awaited_once_with("žluťoučký")

    def _interactive(self, tmp_path, answers):
        target = tmp_path / "p.toml"
        printer = _mock_printer(print_charset_calibration=AsyncMock(return_value=_sheet()))
        replies = iter(answers)

        def fake_input(_prompt):
            try:
                reply = next(replies)
            except StopIteration:
                raise EOFError
            if isinstance(reply, Exception):
                raise reply
            return reply

        with patch("goojprt.cli.GoojPrtPT210", return_value=printer), \
             patch("sys.stdin.isatty", return_value=True), \
             patch.object(builtins, "input", fake_input):
            _run("AA:BB", "--calibrate", "--profile", str(target))
        return target

    def test_the_chosen_letter_is_saved(self, tmp_path, capsys):
        target = self._interactive(tmp_path, ["b"])
        assert load_profile(target) == CANDIDATES[1]
        out = capsys.readouterr().out
        assert f"Saved {CANDIDATES[1].describe()} to {target}" in out

    def test_a_wrong_answer_is_asked_again(self, tmp_path, capsys):
        target = self._interactive(tmp_path, ["x", "9", "c"])
        assert load_profile(target) == CANDIDATES[2]
        assert capsys.readouterr().out.count("Please answer with one of") == 2

    @pytest.mark.parametrize("answers", [[""], ["   "], [EOFError()], ["x", "y", "z"]])
    def test_nothing_is_saved_without_a_valid_answer(self, tmp_path, capsys, answers):
        target = self._interactive(tmp_path, answers)
        assert not target.exists()
        assert "Nothing saved" in capsys.readouterr().out

    @pytest.mark.usefixtures("no_bluetooth")
    def test_calibrate_cannot_be_combined_with_preview(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("AA:BB", "--calibrate", "--preview", "o.png")
        assert exc.value.code == 2


class TestCalibratePick:
    def test_saves_without_touching_the_printer(self, tmp_path, capsys):
        target = tmp_path / "p.toml"
        with patch("goojprt.cli.GoojPrtPT210", side_effect=AssertionError("no connection wanted")):
            _run("--calibrate-pick", "e", "--profile", str(target))
        assert load_profile(target) == CANDIDATES[4]
        assert "Saved" in capsys.readouterr().out

    def test_the_default_location_comes_from_the_environment(self, monkeypatch, tmp_path):
        target = tmp_path / "env" / "p.toml"
        monkeypatch.setenv(PROFILE_ENV, str(target))
        _run("--calibrate-pick", "A")
        assert load_profile(target) == CANDIDATES[0]

    def test_an_unknown_letter_is_a_clear_error(self, tmp_path):
        with pytest.raises(SystemExit, match="not on the sheet"):
            _run("--calibrate-pick", "Z", "--profile", str(tmp_path / "p.toml"))
        assert not (tmp_path / "p.toml").exists()

    def test_it_needs_no_address(self, tmp_path):
        _run("--calibrate-pick", "B", "--profile", str(tmp_path / "p.toml"))
