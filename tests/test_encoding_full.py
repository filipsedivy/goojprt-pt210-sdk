"""Tests for uncovered paths in goojprt.encoding."""
from unittest.mock import patch
from goojprt.encoding import find_system_font, text_to_bytes


def test_find_system_font_returns_none_when_no_candidate_exists():
    with patch("goojprt.encoding.Path") as mock_path:
        mock_path.return_value.exists.return_value = False
        result = find_system_font()
    assert result is None


def test_text_to_bytes_lookup_error_falls_back_to_utf8():
    result = text_to_bytes("hello", encoding="no-such-codec-xyz")
    assert result == "hello".encode("utf-8", errors="replace")
