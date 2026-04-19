"""Tests for goojprt.commands — pure ESC/POS byte builders."""

import pytest
from goojprt.commands import (
    init, align, text_size, bold, underline, feed, line_spacing, cut,
    charset, energy, font, barcode_qr, build_text_block, build_qr_block,
)
from goojprt.enums import Align, TextSize, CodePage


def test_init():
    assert init() == b"\x1b\x40"


def test_align_left():
    result = align(Align.LEFT)
    assert result == bytes([0x1B, 0x61, int(Align.LEFT)])


def test_align_center():
    result = align(Align.CENTER)
    assert result[0:2] == bytes([0x1B, 0x61])
    assert result[2] == int(Align.CENTER)


def test_align_right():
    result = align(Align.RIGHT)
    assert result[2] == int(Align.RIGHT)


def test_text_size_normal():
    result = text_size(TextSize.NORMAL)
    assert result[0:2] == bytes([0x1D, 0x21])
    assert result[2] == int(TextSize.NORMAL)


def test_text_size_double_both():
    result = text_size(TextSize.DOUBLE_BOTH)
    assert result[2] == int(TextSize.DOUBLE_BOTH)


def test_bold_on():
    assert bold(True) == bytes([0x1B, 0x45, 0x01])


def test_bold_off():
    assert bold(False) == bytes([0x1B, 0x45, 0x00])


def test_underline_on():
    assert underline(True) == bytes([0x1B, 0x2D, 0x01])


def test_underline_off():
    assert underline(False) == bytes([0x1B, 0x2D, 0x00])


def test_feed_default():
    result = feed()
    assert result == bytes([0x1B, 0x64, 1])


def test_feed_n():
    result = feed(5)
    assert result == bytes([0x1B, 0x64, 5])


def test_feed_clamped_high():
    result = feed(999)
    assert result == bytes([0x1B, 0x64, 255])


def test_feed_clamped_low():
    result = feed(-1)
    assert result == bytes([0x1B, 0x64, 0])


def test_line_spacing_default():
    result = line_spacing()
    assert result == bytes([0x1B, 0x33, 30])


def test_line_spacing_value():
    result = line_spacing(10)
    assert result == bytes([0x1B, 0x33, 10])


def test_cut():
    assert cut() == bytes([0x1D, 0x56, 0x41, 0x00])


def test_charset_pc437():
    result = charset(CodePage.PC437)
    assert result[0:2] == bytes([0x1B, 0x74])
    assert result[2] == int(CodePage.PC437)


def test_charset_wpc1250():
    result = charset(CodePage.WPC1250)
    assert result[2] == int(CodePage.WPC1250)


def test_energy_default():
    result = energy()
    assert result[0:2] == bytes([0x1B, 0x37])
    assert len(result) == 5


def test_energy_custom():
    result = energy(dots=3, heating=100, interval=5)
    assert result == bytes([0x1B, 0x37, 3, 100, 5])


def test_font_a():
    assert font(False) == bytes([0x1B, 0x4D, 0x00])


def test_font_b():
    assert font(True) == bytes([0x1B, 0x4D, 0x01])


def test_barcode_qr_starts_with_gs():
    result = barcode_qr("hello")
    assert result[:2] == bytes([0x1D, 0x28])


def test_barcode_qr_contains_data():
    data = "https://example.com"
    result = barcode_qr(data)
    assert data.encode("utf-8") in result


def test_barcode_qr_length():
    data = "abc"
    result = barcode_qr(data)
    assert len(result) > len(data)


def test_build_text_block_contains_text():
    result = build_text_block("Hello")
    assert b"Hello" in result


def test_build_text_block_has_newline():
    result = build_text_block("Hello")
    assert result.endswith(b"\n")


def test_build_text_block_no_newline():
    result = build_text_block("Hello", newline=False)
    assert not result.endswith(b"\n")


def test_build_text_block_has_align():
    result = build_text_block("test", align_val=Align.CENTER)
    assert bytes([0x1B, 0x61]) in result


def test_build_qr_block_starts_with_align():
    result = build_qr_block("test")
    assert result[:2] == bytes([0x1B, 0x61])


def test_build_qr_block_ends_with_newline():
    result = build_qr_block("test")
    assert result.endswith(b"\n")


def test_build_qr_block_contains_data():
    result = build_qr_block("mydata")
    assert b"mydata" in result