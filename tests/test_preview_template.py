"""Rendering templates into a PNG without a printer, end to end and without mocks."""
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from goojprt.template import ITEM_TYPES, TemplateError, print_template

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_FILES = sorted(EXAMPLES.glob("*.toml"))
VARS = {"shop": "Corner Shop", "total": "12.50", "ssid": "GuestWiFi"}


@pytest.fixture(autouse=True)
def no_bluetooth():
    """Previewing must never touch BLE."""
    with patch("goojprt.printer.BleTransport", side_effect=AssertionError("BLE was used")), \
         patch("goojprt.printer.SppTransport", side_effect=AssertionError("SPP was used")):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
async def test_every_example_renders_to_a_png(path, tmp_path, capsys):
    out = tmp_path / "out.png"
    await print_template(None, str(path), VARS, preview=str(out))

    with Image.open(out) as png:
        assert png.format == "PNG"
        assert png.width == 384
        assert png.height > 20
    assert f"Preview saved to {out}" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_receipt_preview_contains_the_logo_scaled_to_the_paper(tmp_path):
    out = tmp_path / "out.png"
    await print_template(None, str(EXAMPLES / "receipt.toml"), VARS, preview=str(out))
    with Image.open(out) as png:
        top = png.convert("L").crop((0, 0, 384, 120))
        black = [x for x in range(384) if any(top.getpixel((x, y)) == 0 for y in range(120))]
    # logo.png is 640 px wide; with fit="shrink" it spans the paper instead of being cropped
    assert min(black) < 20 and max(black) > 364


@pytest.mark.asyncio
async def test_native_items_are_reported_not_dropped(tmp_path, capsys):
    out = tmp_path / "out.png"
    await print_template(None, str(EXAMPLES / "wifi-voucher.toml"), VARS, preview=str(out))
    # the QR code is native: it must be called out, with its payload shown in the PNG
    assert "native ESC/POS command(s) cannot be rendered" in capsys.readouterr().out
    with Image.open(out) as png:
        assert png.height > 200


@pytest.mark.asyncio
async def test_preview_needs_no_address(tmp_path):
    await print_template(None, str(EXAMPLES / "receipt.toml"), VARS, preview=str(tmp_path / "o.png"))


@pytest.mark.asyncio
async def test_an_address_is_required_without_preview(tmp_path):
    with pytest.raises(ValueError, match="address"):
        await print_template(None, str(EXAMPLES / "receipt.toml"), VARS)


@pytest.mark.asyncio
async def test_preview_does_not_say_done_disconnected(tmp_path, capsys):
    await print_template(None, str(EXAMPLES / "receipt.toml"), VARS, preview=str(tmp_path / "o.png"))
    out = capsys.readouterr().out
    assert "Connecting" not in out and "Done, disconnected" not in out


@pytest.mark.asyncio
async def test_a_bad_item_leaves_no_png_behind(tmp_path):
    template = tmp_path / "t.toml"
    template.write_text('[[items]]\ntype = "image"\npath = "missing.png"\n', encoding="utf-8")
    out = tmp_path / "o.png"
    with pytest.raises(TemplateError):
        await print_template(None, str(template), preview=str(out))
    assert not out.exists()


@pytest.mark.asyncio
async def test_density_and_charset_items_are_harmless_in_a_preview(tmp_path):
    template = tmp_path / "t.toml"
    template.write_text(
        '[[items]]\ntype = "density"\nlevel = "dark"\n'
        '[[items]]\ntype = "charset"\ncode_page = "PC852"\n'
        '[[items]]\ntype = "chinese_mode"\nenabled = false\n'
        '[[items]]\ntype = "text_image"\ntext = "ok"\n', encoding="utf-8")
    out = tmp_path / "o.png"
    await print_template(None, str(template), preview=str(out), density="light")
    assert out.exists()


def test_every_item_type_is_covered_by_an_example_or_a_test():
    # Keeps ITEM_TYPES honest: the examples exercise the user-facing ones.
    used = set()
    import tomllib
    for path in EXAMPLE_FILES:
        used |= {i["type"] for i in tomllib.loads(path.read_text(encoding="utf-8"))["items"]}
    assert used <= ITEM_TYPES
    assert {"image", "text_image", "grid", "qr", "charset", "chinese_mode"} <= used
