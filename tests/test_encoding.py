"""Tests for goojprt.encoding."""

from pathlib import Path
from goojprt.encoding import text_to_bytes, find_system_font, CODEPAGE_TO_ENCODING
from goojprt.enums import CodePage


def test_ascii_encoding():
    result = text_to_bytes("hello", "ascii")
    assert result == b"hello"


def test_gb2312_default():
    result = text_to_bytes("hello")
    assert result == b"hello"


def test_cp1250_latin_chars():
    result = text_to_bytes("háček", "cp1250")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_unencodable_chars_are_replaced_not_utf8_encoded():
    # Only the unencodable character is lost; the rest keeps the requested codec.
    assert text_to_bytes("café", "ascii") == b"caf?"


def test_unencodable_char_does_not_switch_whole_string_to_utf8():
    # "ř" is not in GB2312, "í" is. UTF-8 bytes would be read as GBK garbage.
    result = text_to_bytes("Příliš", "gb2312")
    assert result == "Příliš".encode("gb2312", errors="replace")
    assert b"\xc3" not in result and b"\xc5" not in result


def test_unencodable_char_logs_char_but_not_the_text(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="goojprt.encoding"):
        text_to_bytes("secret-ř-password", "ascii")
    assert "ř" in caplog.text
    assert "secret" not in caplog.text


def test_wpc1250_std_maps_to_cp1250():
    assert CODEPAGE_TO_ENCODING[CodePage.WPC1250_STD] == "cp1250"
    assert int(CodePage.WPC1250_STD) == 45


def test_fallback_on_unknown_codec():
    result = text_to_bytes("hello", "not-a-real-codec-xyz")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_codepage_to_encoding_has_all_members():
    for member in CodePage:
        assert member in CODEPAGE_TO_ENCODING, f"{member} missing from CODEPAGE_TO_ENCODING"


def test_codepage_to_encoding_values_are_valid_codecs():
    import codecs
    for cp, codec_name in CODEPAGE_TO_ENCODING.items():
        codecs.lookup(codec_name)  # raises LookupError if invalid


def test_find_system_font_returns_str_or_none():
    result = find_system_font()
    assert result is None or isinstance(result, str)


def test_find_system_font_path_exists_if_returned():
    result = find_system_font()
    if result is not None:
        assert Path(result).exists()