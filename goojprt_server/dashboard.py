"""Pinned live dashboard for goojprt-server.

Pure rendering + state. This module does not import ``QueueState``,
``GoojPrtPT210``, or ``Settings``: the lifespan passes pre-computed
values in. That keeps the module unit-testable without FastAPI, BLE, or
the queue.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import logging
import time

from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


@dataclass(frozen=True)
class StaticBanner:
    version: str
    sdk_version: str
    ble_address: str
    host: str
    port: int
    log_level: str
    queue_max: int
    log_file_path: Path | None


@dataclass
class Counters:
    queued: int
    running: int
    done: int
    failed: int


@dataclass
class CurrentJob:
    id: str
    type: str
    started_at: float


@dataclass
class HealthSnapshot:
    battery_pct: int | None
    paper_ok: bool | None


@dataclass
class LiveState:
    ble_connected: bool = False
    ble_reconnecting: bool = False
    ble_reconnect_attempt: int = 0
    counters: Counters = field(default_factory=lambda: Counters(0, 0, 0, 0))
    current_job: CurrentJob | None = None
    health: HealthSnapshot = field(
        default_factory=lambda: HealthSnapshot(battery_pct=None, paper_ok=None)
    )


_SPARK_GLYPHS = "▁▂▃▄▅▆▇█"


def render_sparkline(samples: list[int], max_value: int, width: int) -> str:
    if not samples or width <= 0:
        return ""
    tail = samples[-width:]
    if max_value <= 0:
        return "▁" * len(tail)
    bucket = max(1, max_value)
    out: list[str] = []
    for v in tail:
        v = max(0, min(v, bucket))
        idx = int((v / bucket) * (len(_SPARK_GLYPHS) - 1))
        out.append(_SPARK_GLYPHS[idx])
    return "".join(out)


class Dashboard:
    LOG_BUF_CAPACITY = 500
    SPARKLINE_CAPACITY = 60
    NARROW_WIDTH = 60  # below this, sparkline row is hidden

    def __init__(self, static: StaticBanner) -> None:
        self.static = static
        self.live_state = LiveState()
        self.log_buf: deque[str] = deque(maxlen=self.LOG_BUF_CAPACITY)
        self.sparkline: deque[int] = deque(maxlen=self.SPARKLINE_CAPACITY)
        self._started_at = time.monotonic()
        self.layout = self._build_layout()
        self._live = Live(
            self.layout,
            screen=True,
            refresh_per_second=4,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        self._live_started = False

    def update(self, state: LiveState) -> None:
        self.live_state = state

    def sample_queue(self, depth: int) -> None:
        self.sparkline.append(depth)

    def append_log(self, formatted: str) -> None:
        self.log_buf.append(formatted)

    def start(self) -> None:
        if self._live_started:
            return
        self._live.__enter__()
        self._live_started = True

    def stop(self) -> None:
        if not self._live_started:
            return
        try:
            self._live.__exit__(None, None, None)
        finally:
            self._live_started = False

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=10),
            Layout(name="logs", ratio=1),
        )
        # Use _CallableRenderable so the panel contents re-render on every
        # Live refresh tick instead of capturing a static snapshot.
        layout["header"].update(_CallableRenderable(
            lambda: Panel(self._render_header(),
                          title="GoojPrt PT-210 Print Server",
                          border_style="cyan")))
        layout["logs"].update(_CallableRenderable(
            lambda: Panel(self._render_logs(),
                          title=self._logs_title(),
                          border_style="dim")))
        return layout

    def _logs_title(self) -> str:
        if self.static.log_file_path is not None:
            return f"logs (full in {self.static.log_file_path})"
        return "logs"

    def _render_header(self) -> RenderableType:
        st = self.static
        ls = self.live_state
        if ls.ble_reconnecting:
            ble = f"[yellow]● reconnecting (attempt {ls.ble_reconnect_attempt})[/yellow]"
        elif ls.ble_connected:
            ble = "[green]● connected[/green]"
        else:
            ble = "[red]● disconnected[/red]"
        host_line = Text.from_markup(
            f"[bold]Version:[/bold] {st.version} (sdk {st.sdk_version})"
            f"   [bold]BLE:[/bold] {_short_addr(st.ble_address)}  {ble}"
        )
        listen_line = Text.from_markup(
            f"[bold]Listening:[/bold] http://{st.host}:{st.port}"
            f"     [bold]Log:[/bold] {st.log_level.upper()}"
        )
        c = ls.counters
        counters_line = Text.from_markup(
            f"[bold]Queue:[/bold] {c.queued} queued · {c.running} running · "
            f"{c.done} done · {c.failed} failed  (max {st.queue_max})"
        )
        health_line = Text.from_markup(_render_health(ls.health))
        current_line = Text.from_markup(_render_current_job(ls.current_job))
        rows: list[RenderableType] = [
            host_line, listen_line, counters_line, health_line, current_line,
        ]
        # Sparkline row, hidden on narrow terminals via a measurement hook.
        rows.append(_SparkRow(self.sparkline, self.static.queue_max,
                              self.NARROW_WIDTH))
        return Group(*rows)

    def _render_logs(self) -> RenderableType:
        # Show the last N lines that fit; Rich will clip tall output.
        lines = list(self.log_buf)
        if not lines:
            return Text.from_markup("[dim](no log output yet)[/dim]")
        return Text.from_markup("\n".join(lines[-200:]))


def _short_addr(addr: str) -> str:
    if len(addr) > 17:
        return f"{addr[:4]}…{addr[-8:]}"
    return addr


def _render_health(h: HealthSnapshot) -> str:
    bat = f"{h.battery_pct}%" if h.battery_pct is not None else "[dim]?[/dim]"
    if h.paper_ok is True:
        paper = "paper OK"
    elif h.paper_ok is False:
        paper = "[red]paper OUT[/red]"
    else:
        paper = "[dim]paper ?[/dim]"
    return f"[bold]Printer:[/bold] battery {bat} · {paper}"


def _render_current_job(j: CurrentJob | None) -> str:
    if j is None:
        return "[bold]Current:[/bold]  [dim](idle)[/dim]"
    elapsed = time.monotonic() - j.started_at
    return (f"[bold]Current:[/bold]  {j.id} ({j.type})  "
            f"running {elapsed:.1f}s")


class _CallableRenderable:
    """Minimal Rich renderable that defers to a no-arg callable on each
    render. This is how we keep the Layout live without replacing the
    Layout tree on every tick.
    """

    def __init__(self, fn):
        self._fn = fn

    def __rich_console__(self, console, options):
        yield self._fn()


class _SparkRow:
    """Renders the sparkline row, or nothing if the terminal is narrow."""

    def __init__(self, samples: deque[int], max_value: int, narrow_threshold: int):
        self._samples = samples
        self._max = max_value
        self._narrow = narrow_threshold

    def __rich_console__(self, console, options):
        width = options.max_width
        if width < self._narrow:
            return  # yield nothing
        prefix = "Queue depth (60s):  "
        available = max(0, width - len(prefix))
        # Auto-scale: use the rolling peak (with a small floor) instead of
        # the queue's hard cap, so depths well below the cap still produce
        # readable amplitude. The cap is still the upper bound.
        samples = list(self._samples)
        peak = max(samples, default=0)
        scale = max(5, min(self._max, peak))
        line = render_sparkline(samples, scale, available)
        yield Text.from_markup(f"[bold]Queue depth (60s):[/bold]  {line}")


class DashboardLogHandler(logging.Handler):
    """Formats each record and appends it to the dashboard's log buffer.

    Formatting mirrors ``RichHandler``'s default layout:
    ``[HH:MM:SS] LEVEL  message`` with an optional ``[job=<id>]``
    prefix when the context var is set. Rich markup is stripped so the
    buffer contains plain text; styling is re-applied by the log panel's
    ``Text`` renderable if needed later.
    """

    def __init__(self, dashboard: "Dashboard") -> None:
        super().__init__()
        self._dashboard = dashboard

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        from goojprt_server.logging_setup import job_id_var
        jid = job_id_var.get()
        if jid:
            msg = f"\\[job={jid}] {msg}"
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        line = f"[{ts}] {record.levelname:<7} {msg}"
        self._dashboard.append_log(line)
