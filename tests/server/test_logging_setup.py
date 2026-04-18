import json
import logging
from io import StringIO
from pathlib import Path

import pytest

from goojprt_server.dashboard import Dashboard, StaticBanner
from goojprt_server.logging_setup import configure, glyph, job_id_var


def test_job_id_filter_attaches_var(capsys):
    configure(level="info", json=False)
    log = logging.getLogger("goojprt_server.test")
    job_id_var.set("abc12345")
    log.info("hello")
    captured = capsys.readouterr()
    # Rich writes to stdout; the job id appears in the rendered line.
    assert "abc12345" in captured.out or "abc12345" in captured.err


def test_json_mode_emits_json_line(capsys):
    configure(level="info", json=True)
    log = logging.getLogger("goojprt_server.worker")
    job_id_var.set("deadbeef")
    log.info("job started")
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    obj = json.loads(line)
    assert obj["msg"] == "job started"
    assert obj["level"] == "INFO"
    assert obj["logger"] == "goojprt_server.worker"
    assert obj["job_id"] == "deadbeef"
    assert "ts" in obj


def test_glyph_ascii_fallback(monkeypatch):
    monkeypatch.setenv("GOOJPRT_NO_UNICODE", "1")
    assert glyph("ok") == "OK"
    assert glyph("err") == "ERR"
    monkeypatch.delenv("GOOJPRT_NO_UNICODE")
    assert glyph("ok") == "\u2713"


def _make_static(log_file: Path) -> StaticBanner:
    return StaticBanner(
        version="0.1.0", sdk_version="0.1.0",
        ble_address="AA:BB:CC:DD:EE:FF",
        host="127.0.0.1", port=8080,
        log_level="info", queue_max=100,
        log_file_path=log_file,
    )


def test_dashboard_mode_installs_two_handlers(tmp_path):
    log_file = tmp_path / "s.log"
    d = Dashboard(_make_static(log_file))
    configure(level="info", json=False, dashboard=d, log_file_path=log_file)
    try:
        root = logging.getLogger()
        types = [type(h).__name__ for h in root.handlers]
        assert "DashboardLogHandler" in types
        assert "RotatingFileHandler" in types
        assert "RichHandler" not in types
    finally:
        # Clean up: restore non-dashboard config for other tests.
        configure(level="info", json=False)


def test_dashboard_mode_routes_records_to_buffer_and_file(tmp_path):
    log_file = tmp_path / "s.log"
    d = Dashboard(_make_static(log_file))
    configure(level="info", json=False, dashboard=d, log_file_path=log_file)
    try:
        logging.getLogger("goojprt_server.test").info("hi there")
        # Flush file handler.
        for h in logging.getLogger().handlers:
            h.flush()
        assert any("hi there" in line for line in d.log_buf)
        assert "hi there" in log_file.read_text()
    finally:
        configure(level="info", json=False)


def test_dashboard_mode_creates_parent_dir(tmp_path):
    log_file = tmp_path / "nested" / "x" / "server.log"
    d = Dashboard(_make_static(log_file))
    configure(level="info", json=False, dashboard=d, log_file_path=log_file)
    try:
        assert log_file.parent.exists()
    finally:
        configure(level="info", json=False)


def test_dashboard_mode_file_includes_job_id(tmp_path):
    log_file = tmp_path / "s.log"
    d = Dashboard(_make_static(log_file))
    configure(level="info", json=False, dashboard=d, log_file_path=log_file)
    try:
        job_id_var.set("jobXYZ123")
        logging.getLogger("goojprt_server.test").info("doing work")
        for h in logging.getLogger().handlers:
            h.flush()
        content = log_file.read_text()
        assert "[job=jobXYZ123]" in content
    finally:
        configure(level="info", json=False)


def test_json_mode_ignores_dashboard(tmp_path, capsys):
    log_file = tmp_path / "s.log"
    d = Dashboard(_make_static(log_file))
    configure(level="info", json=True, dashboard=d, log_file_path=log_file)
    try:
        logging.getLogger("goojprt_server.test").info("json wins")
        root = logging.getLogger()
        types = [type(h).__name__ for h in root.handlers]
        # Exactly the JSON stream handler; no dashboard/file handler.
        assert "DashboardLogHandler" not in types
        assert "RotatingFileHandler" not in types
    finally:
        configure(level="info", json=False)


def test_dashboard_none_installs_rich_handler_as_before():
    configure(level="info", json=False)
    root = logging.getLogger()
    types = [type(h).__name__ for h in root.handlers]
    assert "RichHandler" in types
