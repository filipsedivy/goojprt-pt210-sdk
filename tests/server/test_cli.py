import sys

import pytest

from goojprt_server.cli import build_parser, settings_from_args


def test_parser_positional_and_flags():
    p = build_parser()
    ns = p.parse_args([
        "AA:BB:CC:DD:EE:FF",
        "--host", "0.0.0.0",
        "--port", "9000",
        "--log-level", "debug",
        "--log-json",
        "--queue-max-size", "50",
        "--reconnect-interval-s", "1.5",
    ])
    s = settings_from_args(ns)
    assert s.ble_address == "AA:BB:CC:DD:EE:FF"
    assert s.host == "0.0.0.0"
    assert s.port == 9000
    assert s.log_level == "debug"
    assert s.log_json is True
    assert s.queue_max_size == 50
    assert s.reconnect_interval_s == 1.5


def test_env_fallback_when_positional_omitted(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "11:22:33:44:55:66")
    p = build_parser()
    ns = p.parse_args([])
    s = settings_from_args(ns)
    assert s.ble_address == "11:22:33:44:55:66"


from pathlib import Path


def test_no_dashboard_flag():
    p = build_parser()
    ns = p.parse_args(["AA:BB:CC:DD:EE:FF", "--no-dashboard"])
    s = settings_from_args(ns)
    assert s.no_dashboard is True


def test_log_file_flag():
    p = build_parser()
    ns = p.parse_args(["AA:BB:CC:DD:EE:FF", "--log-file", "/tmp/x.log"])
    s = settings_from_args(ns)
    assert s.log_file == Path("/tmp/x.log")


def test_no_log_file_flag():
    p = build_parser()
    ns = p.parse_args(["AA:BB:CC:DD:EE:FF", "--no-log-file"])
    s = settings_from_args(ns)
    assert s.no_log_file is True


def test_defaults_when_flags_absent():
    p = build_parser()
    ns = p.parse_args(["AA:BB:CC:DD:EE:FF"])
    s = settings_from_args(ns)
    assert s.no_dashboard is False
    assert s.log_file is None
    assert s.no_log_file is False


def test_reconnect_job_wait_flag():
    from goojprt_server.cli import build_parser, settings_from_args
    import os
    os.environ.setdefault("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    ns = build_parser().parse_args(["AA:BB:CC:DD:EE:FF", "--reconnect-job-wait", "90"])
    s = settings_from_args(ns)
    assert s.reconnect_job_wait_s == 90.0


def test_reconnect_log_interval_flag():
    from goojprt_server.cli import build_parser, settings_from_args
    import os
    os.environ.setdefault("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    ns = build_parser().parse_args(["AA:BB:CC:DD:EE:FF", "--reconnect-log-interval", "15"])
    s = settings_from_args(ns)
    assert s.reconnect_log_interval_s == 15.0
