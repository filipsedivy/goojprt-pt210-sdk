"""Native text with diacritics: remembered encoding, sticky profile, auto fallback, calibration."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from goojprt import commands
from goojprt.enums import Align, CodePage, TextSize
from goojprt.printer import GoojPrtPT210
from goojprt.profile import CANDIDATES, CZECH_TEST_TEXT, TextProfile
from goojprt.transport.ble import BleTransport
from goojprt.transport.spp import SppTransport

CZ = "Příliš žluťoučký kůň úpěl ďábelské ódy"
FS_DOT = commands.chinese_mode(False)


def _printer() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.is_connected = True
    p._ble.write = AsyncMock()
    p._ble.write_raster_strip = AsyncMock()
    return p


def _writes(p) -> list[bytes]:
    return [c.args[0] for c in p._ble.write.call_args_list]


def _block(text, encoding, **kwargs) -> bytes:
    return commands.build_text_block(text, encoding=encoding, **kwargs)


# ── remembered encoding ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_without_any_state_text_is_gb2312_as_before():
    p = _printer()
    await p.print_text("é")
    assert _writes(p) == [_block("é", "gb2312")]
    assert p.text_encoding is None


@pytest.mark.asyncio
async def test_set_charset_makes_its_codec_the_default():
    p = _printer()
    await p.set_charset(CodePage.PC852)
    await p.print_text("ř")
    assert _writes(p)[-1] == _block("ř", "cp852")
    assert p.text_encoding == "cp852"


@pytest.mark.asyncio
async def test_an_explicit_encoding_always_wins():
    p = _printer()
    await p.set_charset(CodePage.PC852)
    await p.print_text("é", encoding="ascii")
    assert _writes(p)[-1] == _block("é", "ascii")


@pytest.mark.asyncio
async def test_set_charset_for_an_unmapped_table_falls_back_to_gb2312():
    p = _printer()
    await p.set_charset(CodePage.PC852)
    await p.set_charset(7)           # no codec known for it
    assert p.text_encoding is None
    await p.print_text("é")
    assert _writes(p)[-1] == _block("é", "gb2312")


@pytest.mark.asyncio
async def test_initialize_forgets_the_encoding_the_printer_forgot():
    p = _printer()
    await p.set_charset(CodePage.PC852)
    await p.initialize()
    assert p.text_encoding is None
    assert _writes(p)[-1] == commands.init()


def test_spp_text_uses_the_remembered_encoding_too():
    p = GoojPrtPT210()
    p._spp = MagicMock(spec=SppTransport)
    p._text_encoding = "cp852"
    p.print_text_spp("ř")
    p._spp.write.assert_called_once_with(_block("ř", "cp852"))


# ── profiles ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_profile_selects_the_page_and_sets_the_codec():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    assert _writes(p) == [FS_DOT + commands.charset(18)]
    assert p.text_encoding == "cp852"
    await p.print_text(CZ)
    assert _writes(p)[-1] == _block(CZ, "cp852")


@pytest.mark.asyncio
async def test_a_profile_without_chinese_mode_change_sends_no_fs_dot():
    p = _printer()
    await p.apply_profile(TextProfile(45, "cp1250", chinese_mode_off=False))
    assert _writes(p) == [commands.charset(45)]


@pytest.mark.asyncio
async def test_the_profile_survives_initialize_in_a_single_write():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    await p.initialize()
    assert _writes(p) == [commands.init() + FS_DOT + commands.charset(18)]
    assert p.text_encoding == "cp852"


@pytest.mark.asyncio
async def test_clear_profile_goes_back_to_the_defaults():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    await p.clear_profile()
    assert _writes(p) == [commands.init()]
    assert p.text_encoding is None
    await p.initialize()
    assert _writes(p)[-1] == commands.init()


@pytest.mark.asyncio
@pytest.mark.parametrize("page, codec", [(CodePage.PC852, "cp852"), (45, "cp1250"),
                                          (CodePage.ISO8859_2, "iso8859_2"), (39, "iso8859_2")])
async def test_use_codepage_picks_the_usual_codec(page, codec):
    p = _printer()
    await p.use_codepage(page)
    assert p.text_encoding == codec
    assert _writes(p) == [FS_DOT + commands.charset(int(page))]


@pytest.mark.asyncio
async def test_use_codepage_with_an_explicit_codec_and_mode():
    p = _printer()
    await p.use_codepage(7, encoding="cp437", chinese_mode_off=False)
    assert _writes(p) == [commands.charset(7)]
    assert p.text_encoding == "cp437"


@pytest.mark.asyncio
async def test_use_codepage_for_an_unknown_table_needs_a_codec():
    p = _printer()
    with pytest.raises(ValueError, match="no codec"):
        await p.use_codepage(7)
    p._ble.write.assert_not_called()


# ── print_text_auto ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_czech_text_goes_native_with_a_profile():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    await p.print_text_auto(CZ)
    assert _writes(p) == [_block(CZ, "cp852")]
    p._ble.write_raster_strip.assert_not_called()


@pytest.mark.asyncio
async def test_a_character_the_page_lacks_sends_only_that_line_to_the_bitmap_path():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    await p.print_text_auto("První\nCena 5 €\nPoslední")
    assert _writes(p) == [_block("První", "cp852"), _block("Poslední", "cp852")]
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_without_a_profile_only_ascii_is_native():
    p = _printer()
    await p.print_text_auto("plain ASCII")
    assert _writes(p) == [_block("plain ASCII", "gb2312")]
    p._ble.write_raster_strip.assert_not_called()

    p = _printer()
    await p.print_text_auto("kůň")
    p._ble.write.assert_not_called()
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_empty_lines_stay_native_blank_lines():
    p = _printer()
    await p.print_text_auto("a\n\nb")
    assert _writes(p) == [_block("a", "gb2312"), _block("", "gb2312"), _block("b", "gb2312")]


@pytest.mark.asyncio
async def test_native_lines_get_the_styles_and_bitmap_lines_get_font_size_and_alignment():
    p = _printer()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    p.print_text_image = AsyncMock()
    await p.print_text_auto("ok\n€", align=Align.CENTER, bold=True, underline=True,
                            size=TextSize.DOUBLE_BOTH, font_size=30)
    assert _writes(p) == [_block("ok", "cp852", align_val=Align.CENTER, bold_on=True,
                                 underline_on=True, size_val=TextSize.DOUBLE_BOTH)]
    p.print_text_image.assert_awaited_once_with("€", font_size=30, align=Align.CENTER)


@pytest.mark.asyncio
async def test_gb2312_covers_some_accents_natively_in_the_default_chinese_mode():
    p = _printer()
    await p.apply_profile(TextProfile(0, "gb2312", chinese_mode_off=False))
    p._ble.write.reset_mock()
    await p.print_text_auto("é\nř")          # é is in GB2312, ř is not
    assert _writes(p) == [_block("é", "gb2312")]
    assert p._ble.write_raster_strip.called


# ── calibration sheet ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calibration_sheet_prints_every_candidate_with_a_letter():
    p = _printer()
    labels = []
    p.print_text_image = AsyncMock(side_effect=lambda text, **kw: labels.append(text))
    sheet = await p.print_charset_calibration()

    assert list(sheet) == list("ABCDEFGH")
    assert list(sheet.values()) == list(CANDIDATES)
    assert [l[:2] for l in labels[1:]] == [f"{c}:" for c in "ABCDEFGH"]
    lines = [w for w in _writes(p) if CZECH_TEST_TEXT.encode("cp852") in w
             or CZECH_TEST_TEXT.encode("cp1250") in w or CZECH_TEST_TEXT.encode("iso8859_2") in w]
    assert len(lines) == 8
    for (letter, candidate), data in zip(sheet.items(), lines):
        expected = commands.init()
        if candidate.chinese_mode_off:
            expected += FS_DOT
        expected += commands.charset(candidate.code_page) + CZECH_TEST_TEXT.encode(candidate.encoding) + b"\n"
        assert data == expected, letter


@pytest.mark.asyncio
async def test_calibration_sheet_restores_the_applied_profile():
    p = _printer()
    p.print_text_image = AsyncMock()
    await p.apply_profile(TextProfile(18, "cp852"))
    p._ble.write.reset_mock()
    await p.print_charset_calibration()
    assert _writes(p)[-2] == commands.init() + FS_DOT + commands.charset(18)     # final initialize()
    assert p.text_encoding == "cp852"


@pytest.mark.asyncio
async def test_calibration_sheet_without_a_profile_ends_at_the_defaults():
    p = _printer()
    p.print_text_image = AsyncMock()
    await p.print_charset_calibration()
    assert commands.init() in _writes(p)
    assert p.text_encoding is None


@pytest.mark.asyncio
async def test_calibration_sheet_accepts_custom_text_and_candidates():
    p = _printer()
    p.print_text_image = AsyncMock()
    mine = [TextProfile(18, "cp852"), TextProfile(2, "cp850", False)]
    sheet = await p.print_charset_calibration("žluťoučký", mine)
    assert sheet == {"A": mine[0], "B": mine[1]}
    assert "žluťoučký".encode("cp852") + b"\n" in _writes(p)[0]


@pytest.mark.asyncio
async def test_calibration_sheet_replaces_what_the_page_cannot_show():
    p = _printer()
    p.print_text_image = AsyncMock()
    await p.print_charset_calibration("€", [TextProfile(18, "cp852")])
    assert b"?\n" in _writes(p)[0]


@pytest.mark.asyncio
async def test_calibration_sheet_has_a_limit():
    p = _printer()
    with pytest.raises(ValueError, match="at most"):
        await p.print_charset_calibration("x", [TextProfile(18, "cp852")] * 27)


# ── the charset probe is not spoiled by an applied profile ───────────────────

@pytest.mark.asyncio
async def test_probe_variants_without_fs_dot_really_lack_it_when_a_profile_is_applied():
    p = _printer()
    p.print_text_image = AsyncMock()
    await p.apply_profile(TextProfile(18, "cp852"))          # sends FS . + ESC t 18
    p._ble.write.reset_mock()
    await p.probe_charsets(test_string="abc", pages=[CodePage.PC437])

    writes = _writes(p)
    select = commands.charset(CodePage.PC437)                # ESC t 0
    first, second = [i for i, w in enumerate(writes) if w == select]
    assert writes[first - 1] == commands.init()              # plain ESC @, no profile bytes
    assert FS_DOT not in writes[:first]                      # nothing cancelled the Chinese mode yet
    assert writes[second - 1] == FS_DOT                      # only the second variant has it
    assert writes[-2] == commands.init() + FS_DOT + commands.charset(18)   # profile restored at the end
    assert writes[-1] == commands.feed(4)
    assert p.text_encoding == "cp852"
