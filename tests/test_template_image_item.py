"""Template ``image`` item: path resolution, up-front validation, options."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.template import TemplateError, print_template


def _printer() -> MagicMock:
    p = MagicMock()
    for name in ("connect_ble", "initialize", "disconnect", "print_image",
                 "print_text_image", "print_text", "feed"):
        setattr(p, name, AsyncMock())
    return p


def _picture(path: Path, size=(1000, 400)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (0, 0, 0)).save(path)
    return path


async def _run(tmp_path: Path, toml: str, printer: MagicMock, extra=None) -> Path:
    template = tmp_path / "t.toml"
    template.write_text(toml, encoding="utf-8")
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", str(template), extra)
    return template


@pytest.mark.asyncio
async def test_image_item_prints_the_prepared_picture(tmp_path):
    _picture(tmp_path / "logo.png")
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "image"\npath = "logo.png"\n', printer)

    printer.print_image.assert_awaited_once()
    printed = printer.print_image.call_args.args[0]
    assert printed.mode == "1"
    assert printed.width == PAPER_WIDTH_PX
    assert printed.height == 153          # 1000x400 shrunk to 384 wide (400*384/1000 = 153.6, truncated)


@pytest.mark.asyncio
async def test_relative_path_is_resolved_against_the_template_file(tmp_path, monkeypatch):
    _picture(tmp_path / "pics" / "logo.png", size=(100, 50))
    monkeypatch.chdir("/")                # the working directory must not matter
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "image"\npath = "pics/logo.png"\n', printer)
    printer.print_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_absolute_path_and_variable_in_path(tmp_path):
    logo = _picture(tmp_path / "elsewhere" / "logo.png", size=(100, 50))
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "image"\npath = "{{logo}}"\n', printer,
               extra={"logo": str(logo)})
    printer.print_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_options_are_forwarded(tmp_path):
    _picture(tmp_path / "logo.png", size=(100, 50))
    printer = _printer()
    await _run(tmp_path, (
        '[[items]]\ntype = "image"\npath = "logo.png"\n'
        'fit = "width"\nscale = 0.5\nalign = "left"\n'
    ), printer)
    printed = printer.print_image.call_args.args[0]
    black = [x for x in range(printed.width) if printed.getpixel((x, 5)) == 0]
    assert min(black) == 0 and max(black) == PAPER_WIDTH_PX // 2 - 1


@pytest.mark.asyncio
async def test_missing_file_fails_before_the_printer_is_touched(tmp_path):
    printer = _printer()
    toml = (
        '[[items]]\ntype = "text"\ntext = "never printed"\n'
        '[[items]]\ntype = "image"\npath = "nope.png"\n'
    )
    with pytest.raises(TemplateError, match=r"item 2 \(image\).*nope\.png"):
        await _run(tmp_path, toml, printer)
    printer.connect_ble.assert_not_called()
    printer.print_text.assert_not_called()


@pytest.mark.asyncio
async def test_file_that_is_not_an_image_is_reported(tmp_path):
    (tmp_path / "bad.png").write_text("not a png")
    printer = _printer()
    with pytest.raises(TemplateError, match="cannot read"):
        await _run(tmp_path, '[[items]]\ntype = "image"\npath = "bad.png"\n', printer)
    printer.connect_ble.assert_not_called()


@pytest.mark.asyncio
async def test_missing_path_key_is_reported(tmp_path):
    printer = _printer()
    with pytest.raises(TemplateError, match="missing 'path'"):
        await _run(tmp_path, '[[items]]\ntype = "image"\n', printer)


@pytest.mark.asyncio
async def test_invalid_fit_is_reported_as_a_template_error(tmp_path):
    _picture(tmp_path / "logo.png", size=(10, 10))
    printer = _printer()
    with pytest.raises(TemplateError, match="fit"):
        await _run(tmp_path, '[[items]]\ntype = "image"\npath = "logo.png"\nfit = "stretch"\n', printer)
    printer.connect_ble.assert_not_called()


@pytest.mark.asyncio
async def test_text_image_wrap_option_is_forwarded(tmp_path):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "text_image"\ntext = "x"\nwrap = false\n', printer)
    assert printer.print_text_image.call_args.kwargs["wrap"] is False


@pytest.mark.asyncio
async def test_text_image_wraps_by_default(tmp_path):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "text_image"\ntext = "x"\n', printer)
    assert printer.print_text_image.call_args.kwargs["wrap"] is True
