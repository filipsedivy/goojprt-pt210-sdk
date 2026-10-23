"""Template items for native text: codepage, text encoding / auto, and the profile argument."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt.profile import TextProfile
from goojprt.template import TemplateError, print_template

CZ = "Příliš žluťoučký kůň"


def _printer(order=None) -> MagicMock:
    p = MagicMock()
    names = ("connect_ble", "initialize", "disconnect", "print_text", "print_text_auto",
             "apply_profile", "set_density", "print_text_image", "feed")
    for name in names:
        side = (lambda *a, _n=name, **k: order.append(_n)) if order is not None else None
        setattr(p, name, AsyncMock(side_effect=side))
    return p


async def _run(tmp_path: Path, toml: str, printer: MagicMock, **kwargs) -> None:
    template = tmp_path / "t.toml"
    template.write_text(toml, encoding="utf-8")
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", str(template), **kwargs)


def _items(*items: str) -> str:
    return "".join(f"[[items]]\n{item}\n" for item in items)


# ── codepage item ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("item, profile", [
    ('type = "codepage"\ncode_page = "PC852"', TextProfile(18, "cp852", True)),
    ('type = "codepage"\ncode_page = "pc852"', TextProfile(18, "cp852", True)),
    ('type = "codepage"\ncode_page = 45', TextProfile(45, "cp1250", True)),
    ('type = "codepage"\ncode_page = "ISO8859_2"', TextProfile(39, "iso8859_2", True)),
    ('type = "codepage"\ncode_page = 18\nchinese_mode_off = false', TextProfile(18, "cp852", False)),
    ('type = "codepage"\ncode_page = 7\nencoding = "cp437"', TextProfile(7, "cp437", True)),
    ('type = "codepage"\ncode_page = 16\nencoding = "cp1250"', TextProfile(16, "cp1250", True)),
])
async def test_codepage_item_applies_a_profile(tmp_path, item, profile):
    printer = _printer()
    await _run(tmp_path, _items(item), printer)
    printer.apply_profile.assert_awaited_once_with(profile)


@pytest.mark.asyncio
@pytest.mark.parametrize("item, message", [
    ('type = "codepage"\ncode_page = "KLINGON"', "unknown code page"),
    ('type = "codepage"\ncode_page = 7', "no codec is known"),
    ('type = "codepage"\ncode_page = 18\nencoding = "no-such-codec"', "unknown encoding"),
    ('type = "codepage"\ncode_page = 300\nencoding = "cp852"', "code_page"),
    ('type = "codepage"', "code_page is required"),
    ('type = "codepage"\ncode_page = true', "code_page is required"),
    ('type = "codepage"\ncode_page = 18\nchinese_mode_off = "no"', "chinese_mode_off"),
])
async def test_a_bad_codepage_item_fails_before_the_printer_is_touched(tmp_path, item, message):
    printer = _printer()
    with pytest.raises(TemplateError, match=rf"item 2 \(codepage\).*{message}"):
        await _run(tmp_path, _items('type = "text"\ntext = "x"', item), printer)
    printer.connect_ble.assert_not_called()


# ── text items ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_encoding_follows_the_active_page_unless_given(tmp_path):
    printer = _printer()
    await _run(tmp_path, _items('type = "text"\ntext = "a"',
                                'type = "text"\ntext = "b"\nencoding = "cp852"'), printer)
    encodings = [c.kwargs["encoding"] for c in printer.print_text.await_args_list]
    assert encodings == [None, "cp852"]      # None: the printer's active profile, else GB2312


@pytest.mark.asyncio
async def test_auto_text_uses_print_text_auto(tmp_path):
    printer = _printer()
    await _run(tmp_path, _items('type = "text"\ntext = "Cena 5 €"\nauto = true\nbold = true\n'
                                'align = "center"\nsize = "double_both"\nfont_size = 30'), printer)
    printer.print_text.assert_not_called()
    call = printer.print_text_auto.await_args
    assert call.args == ("Cena 5 €",)
    assert call.kwargs["bold"] is True and call.kwargs["font_size"] == 30


@pytest.mark.asyncio
async def test_auto_defaults_to_off(tmp_path):
    printer = _printer()
    await _run(tmp_path, _items('type = "text"\ntext = "x"'), printer)
    printer.print_text_auto.assert_not_called()


# ── profile argument ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_profile_is_applied_after_initialisation_and_density(tmp_path):
    order: list[str] = []
    printer = _printer(order)
    profile = TextProfile(18, "cp852")
    await _run(tmp_path, _items('type = "text"\ntext = "x"'), printer, density="dark", profile=profile)
    assert order == ["connect_ble", "initialize", "set_density", "apply_profile", "print_text", "disconnect"]
    printer.apply_profile.assert_awaited_once_with(profile)


@pytest.mark.asyncio
async def test_a_codepage_item_overrides_the_profile_from_there_on(tmp_path):
    printer = _printer()
    await _run(tmp_path, _items('type = "codepage"\ncode_page = 45'), printer,
               profile=TextProfile(18, "cp852"))
    assert [c.args[0] for c in printer.apply_profile.await_args_list] == [
        TextProfile(18, "cp852"), TextProfile(45, "cp1250")]


@pytest.mark.asyncio
async def test_no_profile_means_no_apply(tmp_path):
    printer = _printer()
    await _run(tmp_path, _items('type = "text"\ntext = "x"'), printer)
    printer.apply_profile.assert_not_called()


# ── end to end through the preview, without mocks ────────────────────────────

@pytest.mark.asyncio
async def test_native_czech_template_renders_in_a_preview(tmp_path, capsys):
    template = tmp_path / "t.toml"
    template.write_text(_items('type = "codepage"\ncode_page = "PC852"',
                               f'type = "text"\ntext = "{CZ}"',
                               'type = "text"\ntext = "Cena 5 €"\nauto = true'), encoding="utf-8")
    out = tmp_path / "o.png"
    with patch("goojprt.printer.BleTransport", side_effect=AssertionError("BLE was used")):
        await print_template(None, str(template), preview=str(out))
    text = capsys.readouterr().out
    assert "1 native ESC/POS command(s)" in text         # the Czech line; the codepage item is silent
    assert "raster strip(s)" in text and "0 raster" not in text      # the euro line became a bitmap
    with Image.open(out) as png:
        assert png.width == 384


@pytest.mark.asyncio
async def test_the_czech_example_prints_its_lines_natively_and_the_euro_line_as_a_bitmap(tmp_path, capsys):
    example = Path(__file__).resolve().parent.parent / "examples" / "native-text-czech.toml"
    with patch("goojprt.printer.BleTransport", side_effect=AssertionError("BLE was used")):
        await print_template(None, str(example), preview=str(tmp_path / "o.png"))
    text = capsys.readouterr().out
    assert "2 native ESC/POS command(s)" in text         # two Czech lines
    assert "raster strip(s)" in text and "0 raster" not in text
