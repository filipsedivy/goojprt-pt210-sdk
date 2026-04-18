from io import StringIO
from pathlib import Path

from rich.console import Console

from goojprt_server.dashboard import (
    Counters,
    CurrentJob,
    Dashboard,
    HealthSnapshot,
    LiveState,
    StaticBanner,
)


def _make_static() -> StaticBanner:
    return StaticBanner(
        version="0.1.0",
        sdk_version="0.1.0",
        ble_address="AA:BB:CC:DD:EE:FF",
        host="127.0.0.1",
        port=8080,
        log_level="info",
        queue_max=100,
        log_file_path=Path("/tmp/server.log"),
    )


def test_counters_default_zero():
    c = Counters(0, 0, 0, 0)
    assert c.queued == 0 and c.running == 0 and c.done == 0 and c.failed == 0


def test_live_state_defaults():
    s = LiveState()
    assert s.ble_connected is False
    assert s.counters == Counters(0, 0, 0, 0)
    assert s.current_job is None
    assert s.health == HealthSnapshot(battery_pct=None, paper_ok=None)


def test_dashboard_sample_queue_bounded_to_60():
    d = Dashboard(_make_static())
    for i in range(100):
        d.sample_queue(i)
    assert len(d.sparkline) == 60
    assert list(d.sparkline)[0] == 40  # oldest of the kept window
    assert list(d.sparkline)[-1] == 99


def test_dashboard_append_log_bounded_to_500():
    d = Dashboard(_make_static())
    for i in range(1000):
        d.append_log(f"line {i}")
    assert len(d.log_buf) == 500
    assert list(d.log_buf)[0] == "line 500"
    assert list(d.log_buf)[-1] == "line 999"


def test_dashboard_update_replaces_state():
    d = Dashboard(_make_static())
    d.update(LiveState(ble_connected=True,
                       counters=Counters(1, 2, 3, 4),
                       current_job=CurrentJob(id="abc", type="text", started_at=10.0),
                       health=HealthSnapshot(battery_pct=80, paper_ok=True)))
    assert d.live_state.ble_connected is True
    assert d.live_state.counters.running == 2
    assert d.live_state.current_job.id == "abc"
    assert d.live_state.health.battery_pct == 80


def _render(d, width=80):
    """Render the dashboard layout to a plain string (no ANSI)."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width,
                      color_system=None, legacy_windows=False)
    console.print(d.layout)
    return buf.getvalue()


def test_render_contains_static_banner_fields():
    d = Dashboard(_make_static())
    out = _render(d)
    assert "0.1.0" in out
    assert "AA:BB:CC:DD:EE:FF" in out
    assert "127.0.0.1:8080" in out
    assert "INFO" in out


def test_render_shows_counters():
    d = Dashboard(_make_static())
    d.update(LiveState(counters=Counters(queued=3, running=1, done=42, failed=1)))
    out = _render(d)
    assert "3 queued" in out
    assert "1 running" in out
    assert "42 done" in out
    assert "1 failed" in out


def test_render_shows_current_job_when_running():
    d = Dashboard(_make_static())
    d.update(LiveState(current_job=CurrentJob(id="7f3a1b2c", type="text",
                                              started_at=0.0)))
    out = _render(d)
    assert "7f3a1b2c" in out
    assert "text" in out


def test_render_hides_current_job_when_none():
    d = Dashboard(_make_static())
    out = _render(d)
    assert "Current:" in out  # label still there
    assert "(idle)" in out    # with idle marker


def test_render_shows_health_when_known():
    d = Dashboard(_make_static())
    d.update(LiveState(health=HealthSnapshot(battery_pct=78, paper_ok=True)))
    out = _render(d)
    assert "78%" in out
    assert "OK" in out or "ok" in out


def test_render_shows_ble_state():
    d = Dashboard(_make_static())
    d.update(LiveState(ble_connected=True))
    assert "connected" in _render(d)
    d.update(LiveState(ble_connected=False))
    assert "reconnecting" in _render(d) or "disconnected" in _render(d)


def test_render_sparkline_glyphs_present():
    d = Dashboard(_make_static())
    for i in range(10):
        d.sample_queue(i)
    out = _render(d)
    # Any of the sparkline glyphs should appear
    assert any(g in out for g in "▁▂▃▄▅▆▇█")


def test_render_shows_recent_log_lines():
    d = Dashboard(_make_static())
    for i in range(5):
        d.append_log(f"logline-{i}")
    out = _render(d)
    assert "logline-4" in out
    assert "logline-3" in out


def test_render_narrow_terminal_hides_sparkline():
    d = Dashboard(_make_static())
    for i in range(30):
        d.sample_queue(i)
    out = _render(d, width=35)
    # With very narrow width, the sparkline row should not take space
    assert "Queue depth" not in out


import logging

from goojprt_server.dashboard import DashboardLogHandler
from goojprt_server.logging_setup import job_id_var


def test_dashboard_log_handler_appends_to_buffer():
    d = Dashboard(_make_static())
    h = DashboardLogHandler(d)
    h.setLevel(logging.INFO)
    log = logging.getLogger("test_dashboard_handler.a")
    log.handlers = [h]
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("hello from test")
    assert any("hello from test" in line for line in d.log_buf)


def test_dashboard_log_handler_includes_job_id():
    d = Dashboard(_make_static())
    h = DashboardLogHandler(d)
    h.setLevel(logging.INFO)
    log = logging.getLogger("test_dashboard_handler.b")
    log.handlers = [h]
    log.setLevel(logging.INFO)
    log.propagate = False
    token = job_id_var.set("deadbeef")
    try:
        log.info("with job id")
    finally:
        job_id_var.reset(token)
    assert any("deadbeef" in line and "with job id" in line for line in d.log_buf)


def test_dashboard_log_handler_level_string_present():
    d = Dashboard(_make_static())
    h = DashboardLogHandler(d)
    h.setLevel(logging.WARNING)
    log = logging.getLogger("test_dashboard_handler.c")
    log.handlers = [h]
    log.setLevel(logging.WARNING)
    log.propagate = False
    log.warning("careful")
    assert any("WARNING" in line and "careful" in line for line in d.log_buf)


def test_dashboard_start_stop_is_idempotent_safe(monkeypatch):
    """``start`` enters Live; ``stop`` exits it. Both tolerate re-entry."""
    d = Dashboard(_make_static())
    entered = {"n": 0}
    exited = {"n": 0}

    class FakeLive:
        def __enter__(self):
            entered["n"] += 1
            return self

        def __exit__(self, *exc):
            exited["n"] += 1
            return False

    d._live = FakeLive()  # type: ignore[attr-defined]
    d.start()
    d.start()  # second start is a no-op
    d.stop()
    d.stop()  # second stop is a no-op
    assert entered["n"] == 1
    assert exited["n"] == 1


def test_dashboard_builds_real_live_by_default():
    from rich.live import Live
    d = Dashboard(_make_static())
    assert isinstance(d._live, Live)  # type: ignore[attr-defined]


def test_sparkline_autoscales_for_low_depth():
    """A handful of small queue depths should produce visible amplitude,
    not a flat line of the lowest glyph."""
    d = Dashboard(_make_static())  # queue_max=100
    for v in [0, 1, 2, 3, 4, 5]:
        d.sample_queue(v)
    out = _render(d)
    glyphs_seen = {g for g in "▁▂▃▄▅▆▇█" if g in out}
    # Auto-scale should produce more than one distinct glyph.
    assert len(glyphs_seen) > 1, (
        f"sparkline collapsed to one glyph: {glyphs_seen!r}"
    )


def test_sparkline_clamped_to_queue_max():
    """Even with auto-scale, values stay clamped to the configured max."""
    from goojprt_server.dashboard import render_sparkline
    # peak == queue_max → behaves like the original cap.
    line = render_sparkline([100, 100, 100], 100, 10)
    assert line == "█" * 3


def test_dashboard_reconnecting_indicator():
    d = Dashboard(_make_static())
    d.update(LiveState(
        ble_connected=False,
        ble_reconnecting=True,
        ble_reconnect_attempt=3,
        counters=Counters(0, 0, 0, 0),
        health=HealthSnapshot(None, None),
    ))
    out = _render(d)
    assert "reconnecting" in out.lower()
    assert "3" in out


def test_dashboard_connected_indicator():
    d = Dashboard(_make_static())
    d.update(LiveState(
        ble_connected=True,
        ble_reconnecting=False,
        ble_reconnect_attempt=0,
        counters=Counters(0, 0, 0, 0),
        health=HealthSnapshot(None, None),
    ))
    out = _render(d)
    assert "connected" in out.lower()
