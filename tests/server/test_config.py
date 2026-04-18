import pytest
from goojprt_server.config import Settings


def test_defaults_applied(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    s = Settings()
    assert s.ble_address == "AA:BB:CC:DD:EE:FF"
    assert s.host == "127.0.0.1"
    assert s.port == 8080
    assert s.log_level == "info"
    assert s.log_json is False
    assert s.queue_max_size == 100
    assert s.reconnect_interval_s == 5.0
    assert s.job_ttl_s == 3600
    assert s.cors_origins == []


def test_env_override(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("GOOJPRT_PORT", "9000")
    monkeypatch.setenv("GOOJPRT_LOG_JSON", "true")
    monkeypatch.setenv("GOOJPRT_CORS_ORIGINS", "http://a.test,http://b.test")
    s = Settings()
    assert s.port == 9000
    assert s.log_json is True
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_ble_address_required(monkeypatch):
    monkeypatch.delenv("GOOJPRT_BLE_ADDRESS", raising=False)
    with pytest.raises(Exception):
        Settings()


from pathlib import Path


def test_dashboard_fields_default(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    s = Settings()
    assert s.no_dashboard is False
    assert s.log_file is None
    assert s.no_log_file is False


def test_log_file_accepts_path(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    s = Settings(log_file=Path("/tmp/goojprt.log"))
    assert s.log_file == Path("/tmp/goojprt.log")


def test_log_file_from_env(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("GOOJPRT_LOG_FILE", "/var/log/goojprt.log")
    s = Settings()
    assert s.log_file == Path("/var/log/goojprt.log")


def test_reconnect_job_wait_default(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    s = Settings()
    assert s.reconnect_job_wait_s == 60.0


def test_reconnect_log_interval_default(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    s = Settings()
    assert s.reconnect_log_interval_s == 30.0


def test_reconnect_settings_via_env(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("GOOJPRT_RECONNECT_JOB_WAIT_S", "120.0")
    monkeypatch.setenv("GOOJPRT_RECONNECT_LOG_INTERVAL_S", "10.0")
    s = Settings()
    assert s.reconnect_job_wait_s == 120.0
    assert s.reconnect_log_interval_s == 10.0
