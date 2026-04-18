from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

from goojprt_server.app import create_app
from goojprt_server.config import Settings
from goojprt_server.lifespan import build_lifespan
from tests.server.fake_printer import FakePrinter


@pytest.mark.asyncio
async def test_non_tty_skips_dashboard(monkeypatch, tmp_path):
    """On a non-TTY (pytest default), dashboard must not start."""
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3)
    fake = FakePrinter()
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            assert getattr(app.state, "dashboard", None) is None
            assert getattr(app.state, "sparkline_task", "MISSING") is None


@pytest.mark.asyncio
async def test_explicit_no_dashboard_flag(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3, no_dashboard=True)
    fake = FakePrinter()
    # Pretend we ARE a TTY; flag must still disable dashboard.
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            assert getattr(app.state, "dashboard", None) is None


@pytest.mark.asyncio
async def test_json_mode_skips_dashboard(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3, log_json=True)
    fake = FakePrinter()
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            assert getattr(app.state, "dashboard", None) is None


@pytest.mark.asyncio
async def test_dashboard_start_failure_falls_back(monkeypatch, caplog):
    """If Dashboard.start() raises, lifespan must continue with streaming."""
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3)
    fake = FakePrinter()
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    def boom(self):
        raise RuntimeError("no TTY for Live")

    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake), \
         patch("goojprt_server.dashboard.Dashboard.start", boom):
        app = create_app(settings=settings)
        with caplog.at_level(logging.WARNING):
            async with build_lifespan(settings)(app):
                assert getattr(app.state, "dashboard", None) is None
        assert any("dashboard disabled" in rec.message.lower()
                   for rec in caplog.records)


from goojprt_server.dashboard import Counters, Dashboard, StaticBanner
from goojprt_server.lifespan import (
    _aggregate_counters, _find_running_job,
)
from goojprt_server.queue import Job, JobRegistry


def _mk_job(id: str, status: str, started_at: float | None = None) -> Job:
    return Job(id=id, type="text", payload={}, status=status,
               created_at=0.0, started_at=started_at,
               finished_at=None, error=None)


def test_aggregate_counters_from_registry():
    reg = JobRegistry()
    reg.add(_mk_job("a", "queued"))
    reg.add(_mk_job("b", "running", started_at=1.0))
    reg.add(_mk_job("c", "done"))
    reg.add(_mk_job("d", "done"))
    reg.add(_mk_job("e", "failed"))
    c = _aggregate_counters(reg, queue_depth=2)
    # queue_depth dominates the 'queued' counter (asyncio.Queue is the
    # authoritative source for pending items); registry 'queued' is
    # redundant info.
    assert c.queued == 2
    assert c.running == 1
    assert c.done == 2
    assert c.failed == 1


def test_find_running_job_returns_first():
    reg = JobRegistry()
    reg.add(_mk_job("a", "done"))
    reg.add(_mk_job("b", "running", started_at=1.0))
    reg.add(_mk_job("c", "running", started_at=2.0))
    j = _find_running_job(reg)
    assert j is not None
    assert j.id in {"b", "c"}
    assert j.type == "text"
    assert j.started_at in (1.0, 2.0)


def test_find_running_job_none_when_idle():
    reg = JobRegistry()
    reg.add(_mk_job("a", "done"))
    assert _find_running_job(reg) is None


@pytest.mark.asyncio
async def test_sampler_and_refresh_run_when_dashboard_active(monkeypatch):
    """When the dashboard is active, both background tasks live on app.state."""
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3)
    fake = FakePrinter()
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    # Make Dashboard.start a no-op so we don't actually enter Live.
    monkeypatch.setattr(Dashboard, "start", lambda self: None)
    monkeypatch.setattr(Dashboard, "stop", lambda self: None)

    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            assert app.state.dashboard is not None
            assert hasattr(app.state, "sparkline_task")
            assert hasattr(app.state, "dashboard_refresh_task")
            # Let the loops tick at least once.
            await asyncio.sleep(0.4)
            assert len(app.state.dashboard.sparkline) >= 1


@pytest.mark.asyncio
async def test_lifespan_sets_monitor_on_app_state(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3)
    fake = FakePrinter()
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            from goojprt_server.connection_monitor import ConnectionMonitor
            assert isinstance(app.state.monitor, ConnectionMonitor)
            assert app.state.monitor.is_reconnecting is False
