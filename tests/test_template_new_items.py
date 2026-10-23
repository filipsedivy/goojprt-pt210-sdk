"""Tests for the charset / chinese_mode template items and the shipped examples."""
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt.enums import CodePage
from goojprt.template import ITEM_TYPES, build_vars, print_template, substitute_deep

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _printer() -> MagicMock:
    p = MagicMock()
    for name in (
        "connect_ble", "initialize", "disconnect", "print_text_image", "print_text",
        "print_pdf417", "print_qr", "print_line", "feed", "cut", "print_grid",
        "print_ekg", "set_charset", "set_chinese_mode", "print_image",
    ):
        setattr(p, name, AsyncMock())
    return p


async def _run(tmp_path: Path, toml: str, printer: MagicMock) -> None:
    path = tmp_path / "t.toml"
    path.write_text(toml, encoding="utf-8")
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", str(path))


@pytest.mark.asyncio
async def test_charset_item_selects_code_page_by_name(tmp_path):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "charset"\ncode_page = "pc852"\n', printer)
    printer.set_charset.assert_awaited_once_with(CodePage.PC852)


@pytest.mark.asyncio
async def test_charset_item_accepts_the_standard_cp1250_slot(tmp_path):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "charset"\ncode_page = "WPC1250_STD"\n', printer)
    printer.set_charset.assert_awaited_once_with(CodePage.WPC1250_STD)


@pytest.mark.asyncio
async def test_charset_item_with_unknown_name_is_skipped_with_hint(tmp_path, capsys):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "charset"\ncode_page = "KLINGON"\n', printer)
    printer.set_charset.assert_not_called()
    out = capsys.readouterr().out
    assert "Unknown code page 'KLINGON'" in out
    assert "PC852" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_chinese_mode_item(tmp_path, enabled):
    printer = _printer()
    await _run(
        tmp_path,
        f'[[items]]\ntype = "chinese_mode"\nenabled = {str(enabled).lower()}\n',
        printer,
    )
    printer.set_chinese_mode.assert_awaited_once_with(enabled)


@pytest.mark.asyncio
async def test_chinese_mode_item_defaults_to_off(tmp_path):
    printer = _printer()
    await _run(tmp_path, '[[items]]\ntype = "chinese_mode"\n', printer)
    printer.set_chinese_mode.assert_awaited_once_with(False)


# ── shipped examples ──────────────────────────────────────────────────────────

EXAMPLE_FILES = sorted(EXAMPLES.glob("*.toml"))


def test_examples_exist():
    # The CLI help points users at examples/.
    assert EXAMPLE_FILES, f"no example templates in {EXAMPLES}"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_uses_only_supported_item_types(path):
    items = tomllib.loads(path.read_text(encoding="utf-8"))["items"]
    assert items
    assert {item["type"] for item in items} <= ITEM_TYPES


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_variables_are_all_resolvable(path):
    # Every {{variable}} is either built in or documented as a --var in the header.
    import re

    text = path.read_text(encoding="utf-8")
    used = set(re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text))
    documented = set(re.findall(r"--var\s+([A-Za-z0-9_]+)=", text))
    unresolved = used - set(build_vars()) - documented
    assert not unresolved, f"{path.name}: undocumented variables {sorted(unresolved)}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
async def test_example_prints_end_to_end_against_a_mock_printer(path):
    printer = _printer()
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template(
            "AA:BB", str(path),
            {"shop": "Corner Shop", "total": "12.50", "ssid": "GuestWiFi"},
        )
    printer.initialize.assert_awaited_once()
    printer.disconnect.assert_awaited_once()
    printed = [
        name for name in ("print_text", "print_text_image", "print_qr", "print_grid",
                          "print_line", "print_image", "set_charset", "set_chinese_mode")
        if getattr(printer, name).await_count
    ]
    assert printed, "the template printed nothing"


def test_wifi_voucher_password_is_identical_in_qr_and_text():
    variables = build_vars({"ssid": "GuestWiFi"})
    items = tomllib.loads((EXAMPLES / "wifi-voucher.toml").read_text(encoding="utf-8"))["items"]
    items = substitute_deep(items, variables)
    qr = next(i for i in items if i["type"] == "qr")["data"]
    text = next(i for i in items if i["type"] == "text_image" and "Password" in i["text"])["text"]
    password = variables["password_12"]
    assert f"P:{password};" in qr
    assert f"Password: {password}" in text
