"""Tests for goojprt.status — DLE EOT response decoding."""

import pytest

from goojprt import commands, status


def test_status_request_bytes():
    assert commands.status_request(4) == b"\x10\x04\x04"


def test_info_request_bytes():
    assert commands.info_request(1) == b"\x1d\x49\x01"


def test_chinese_mode_bytes():
    assert commands.chinese_mode(False) == b"\x1c\x2e"  # FS .
    assert commands.chinese_mode(True) == b"\x1c\x26"   # FS &


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_all_clear_byte_is_ok_and_has_no_flags_set(n):
    assert status.status_ok(n, 0x00) is True
    assert not any(status.decode_status(n, 0x00).values())


def test_printer_offline():
    assert status.decode_status(status.PRINTER, 0x08) == {"offline": True}
    assert status.status_ok(status.PRINTER, 0x08) is False


def test_offline_cause_flags():
    flags = status.decode_status(status.OFFLINE_CAUSE, 0x04 | 0x20 | 0x40)
    assert flags == {
        "cover_open": True, "feed_button": False, "paper_end": True, "error": True,
    }


def test_feed_button_alone_is_not_a_fault():
    # Some firmware keeps this bit set permanently.
    assert status.decode_status(status.OFFLINE_CAUSE, 0x08)["feed_button"] is True
    assert status.status_ok(status.OFFLINE_CAUSE, 0x08) is True


def test_cover_open_is_a_fault():
    assert status.status_ok(status.OFFLINE_CAUSE, 0x04) is False


def test_error_cause_flags():
    flags = status.decode_status(status.ERROR_CAUSE, 0x08 | 0x20 | 0x40)
    assert flags == {
        "cutter_error": True, "unrecoverable_error": True, "recoverable_error": True,
    }


@pytest.mark.parametrize("byte, low, end", [
    (0x00, False, False),   # paper adequate
    (0x0C, True, False),    # near end
    (0x60, False, True),    # paper end
    (0x6C, True, True),     # both, as many printers report an empty roll
])
def test_paper_sensor(byte, low, end):
    flags = status.decode_status(status.PAPER_SENSOR, byte)
    assert flags == {"paper_low": low, "paper_end": end}
    assert status.status_ok(status.PAPER_SENSOR, byte) is (not (low or end))


@pytest.mark.parametrize("bad", [0, 5, 65, -1])
def test_unknown_request_raises(bad):
    with pytest.raises(ValueError, match="expected 1-4"):
        status.decode_status(bad, 0)
    with pytest.raises(ValueError):
        status.status_ok(bad, 0)
