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


def test_fallback_on_unicode_error():
    # Characters not in ASCII fall back to UTF-8
    result = text_to_bytes("café", "ascii")
    assert isinstance(result, bytes)
    assert len(result) > 0


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