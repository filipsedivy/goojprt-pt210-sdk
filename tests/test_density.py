"""Print density: presets, range validation, facade method and template item."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt import commands
from goojprt.printer import GoojPrtPT210
from goojprt.template import TemplateError, print_template
from goojprt.transport.ble import BleTransport


# ── commands ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, heating", [("light", 60), ("normal", 80), ("dark", 120),
                                           ("DARK", 120), ("Light", 60)])
def test_presets_resolve_case_insensitively(name, heating):
    assert commands.resolve_density(name) == heating


@pytest.mark.parametrize("value", [0, 1, 99, 255])
def test_numbers_pass_through(value):
    assert commands.resolve_density(value) == value


@pytest.mark.parametrize("bad", [-1, 256, 1000, "darkest", "", None, 80.0, True])
def test_bad_density_is_rejected(bad):
    with pytest.raises(ValueError):
        commands.resolve_density(bad)


def test_error_message_lists_the_presets():
    with pytest.raises(ValueError, match="light, normal, dark"):
        commands.resolve_density("darkest")


@pytest.mark.parametrize("kwargs", [
    {"dots": 256}, {"dots": -1}, {"heating": 256}, {"heating": -5}, {"interval": 300},
])
def test_energy_rejects_values_that_would_wrap_around(kwargs):
    with pytest.raises(ValueError, match="0-255"):
        commands.energy(**kwargs)


def test_energy_accepts_the_byte_limits():
    assert commands.energy(dots=0, heating=255, interval=0) == bytes([0x1B, 0x37, 0, 255, 0])


# ── facade ────────────────────────────────────────────────────────────────────

def _printer() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.write = AsyncMock()
    return p


@pytest.mark.asyncio
@pytest.mark.parametrize("level, expected", [
    ("normal", bytes([0x1B, 0x37, 7, 80, 2])),
    ("dark", bytes([0x1B, 0x37, 7, 120, 2])),
    ("light", bytes([0x1B, 0x37, 7, 60, 2])),
    (99, bytes([0x1B, 0x37, 7, 99, 2])),
])
async def test_set_density_sends_esc_7(level, expected):
    p = _printer()
    await p.set_density(level)
    p._ble.write.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_set_density_defaults_to_normal():
    p = _printer()
    await p.set_density()
    p._ble.write.assert_awaited_once_with(bytes([0x1B, 0x37, 7, 80, 2]))


@pytest.mark.asyncio
async def test_set_density_passes_dots_and_interval():
    p = _printer()
    await p.set_density("dark", dots=3, interval=5)
    p._ble.write.assert_awaited_once_with(bytes([0x1B, 0x37, 3, 120, 5]))


@pytest.mark.asyncio
@pytest.mark.parametrize("args, kwargs", [
    (("darkest",), {}), ((300,), {}), (("dark",), {"dots": 999}), (("dark",), {"interval": -1}),
])
async def test_invalid_density_sends_nothing(args, kwargs):
    p = _printer()
    with pytest.raises(ValueError):
        await p.set_density(*args, **kwargs)
    p._ble.write.assert_not_called()


# ── template ──────────────────────────────────────────────────────────────────

def _template_printer(order: list[str]) -> MagicMock:
    p = MagicMock()
    p.connect_ble = AsyncMock(side_effect=lambda *a, **k: order.append("connect"))
    p.initialize = AsyncMock(side_effect=lambda: order.append("initialize"))
    p.disconnect = AsyncMock()
    p.set_density = AsyncMock(side_effect=lambda *a, **k: order.append("density"))
    p.print_text = AsyncMock(side_effect=lambda *a, **k: order.append("text"))
    return p


async def _run(tmp_path: Path, toml: str, printer: MagicMock, **kwargs) -> None:
    template = tmp_path / "t.toml"
    template.write_text(toml, encoding="utf-8")
    with patch("goojprt.template.GoojPrtPT210", return_value=printer):
        await print_template("AA:BB", str(template), **kwargs)


@pytest.mark.asyncio
async def test_density_item_with_level(tmp_path):
    order: list[str] = []
    printer = _template_printer(order)
    await _run(tmp_path, '[[items]]\ntype = "density"\nlevel = "dark"\n'
                         '[[items]]\ntype = "text"\ntext = "x"\n', printer)
    printer.set_density.assert_awaited_once_with("dark", dots=7, interval=2)
    assert order == ["connect", "initialize", "density", "text"]


@pytest.mark.asyncio
async def test_density_item_with_heating_dots_and_interval(tmp_path):
    printer = _template_printer([])
    await _run(tmp_path, '[[items]]\ntype = "density"\nheating = 100\ndots = 5\ninterval = 3\n', printer)
    printer.set_density.assert_awaited_once_with(100, dots=5, interval=3)


@pytest.mark.asyncio
async def test_density_item_without_settings_means_normal(tmp_path):
    printer = _template_printer([])
    await _run(tmp_path, '[[items]]\ntype = "density"\n', printer)
    printer.set_density.assert_awaited_once_with("normal", dots=7, interval=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("item", [
    'level = "darkest"', "heating = 999", 'heating = "hot"', "dots = 300",
])
async def test_bad_density_item_fails_before_connecting(tmp_path, item):
    printer = _template_printer([])
    with pytest.raises(TemplateError, match=r"item 2 \(density\)"):
        await _run(tmp_path, '[[items]]\ntype = "text"\ntext = "x"\n'
                             f'[[items]]\ntype = "density"\n{item}\n', printer)
    printer.connect_ble.assert_not_called()


@pytest.mark.asyncio
async def test_density_argument_is_applied_right_after_initialize(tmp_path):
    order: list[str] = []
    printer = _template_printer(order)
    await _run(tmp_path, '[[items]]\ntype = "text"\ntext = "x"\n', printer, density="dark")
    printer.set_density.assert_awaited_once_with("dark")
    assert order == ["connect", "initialize", "density", "text"]


@pytest.mark.asyncio
async def test_a_density_item_overrides_the_density_argument(tmp_path):
    printer = _template_printer([])
    await _run(tmp_path, '[[items]]\ntype = "density"\nlevel = "light"\n', printer, density="dark")
    assert [c.args[0] for c in printer.set_density.await_args_list] == ["dark", "light"]


@pytest.mark.asyncio
async def test_bad_density_argument_fails_before_connecting(tmp_path):
    printer = _template_printer([])
    with pytest.raises(TemplateError, match="density"):
        await _run(tmp_path, '[[items]]\ntype = "text"\ntext = "x"\n', printer, density="darkest")
    printer.connect_ble.assert_not_called()


@pytest.mark.asyncio
async def test_no_density_means_the_printer_is_left_alone(tmp_path):
    printer = _template_printer([])
    await _run(tmp_path, '[[items]]\ntype = "text"\ntext = "x"\n', printer)
    printer.set_density.assert_not_called()
