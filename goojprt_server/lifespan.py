"""FastAPI lifespan for the print server."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from goojprt import GoojPrtPT210
from goojprt_server import __version__, printer_holder
from goojprt_server.config import Settings
from goojprt_server.dashboard import (
    Counters, CurrentJob, Dashboard, HealthSnapshot, LiveState, StaticBanner,
)
from goojprt_server.log_paths import default_server_log_path
from goojprt_server.logging_setup import configure, glyph, print_banner
from goojprt_server.connection_monitor import ConnectionMonitor, run_monitor
from goojprt_server.queue import Job, JobRegistry, QueueState
from goojprt_server.worker import run_worker

log = logging.getLogger("goojprt_server.server")
ble_log = logging.getLogger("goojprt_server.ble")


async def _ttl_sweep(qs: QueueState, ttl_s: float) -> None:
    while True:
        try:
            removed = qs.registry.sweep(ttl_s)
            if removed:
                logging.getLogger("goojprt_server.queue").debug(
                    "swept %d stale jobs", removed
                )
        except Exception:  # noqa: BLE001
            log.exception("ttl sweep crashed; continuing")
        await asyncio.sleep(60)


async def _health_refresh(app_state, printer) -> None:
    while True:
        try:
            if printer.is_connected_ble:
                info = await printer.query_full_info(timeout=1.0)
                cache = {}
                lvl = info.get("ble_battery", {}).get("level_pct")
                if isinstance(lvl, int):
                    cache["battery_pct"] = lvl
                paper = info.get("escpos_status", {}).get("paper", {})
                if "ok" in paper:
                    cache["paper_ok"] = bool(paper["ok"])
                app_state.health_cache = cache
        except Exception:  # noqa: BLE001
            ble_log.debug("health refresh failed (ignored)", exc_info=True)
        await asyncio.sleep(30)


def _resolve_log_file(settings: Settings) -> Path | None:
    """Return the log file path for dashboard mode, or ``None`` to skip."""
    if settings.no_log_file:
        return None
    if settings.log_file is not None:
        return settings.log_file
    return default_server_log_path()


def _dashboard_enabled(settings: Settings) -> bool:
    if settings.log_json:
        return False
    if settings.no_dashboard:
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _build_dashboard(settings: Settings) -> Dashboard:
    try:
        from goojprt import __version__ as sdk_version
    except ImportError:
        sdk_version = "unknown"
    static = StaticBanner(
        version=__version__,
        sdk_version=sdk_version,
        ble_address=settings.ble_address,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        queue_max=settings.queue_max_size,
        log_file_path=_resolve_log_file(settings),
    )
    return Dashboard(static)


def _aggregate_counters(registry: JobRegistry, queue_depth: int) -> Counters:
    running = done = failed = 0
    for j in registry.iter_jobs():
        if j.status == "running":
            running += 1
        elif j.status == "done":
            done += 1
        elif j.status == "failed":
            failed += 1
    return Counters(queued=queue_depth, running=running, done=done, failed=failed)


def _find_running_job(registry: JobRegistry) -> CurrentJob | None:
    for j in registry.iter_jobs():
        if j.status == "running" and j.started_at is not None:
            return CurrentJob(id=j.id, type=j.type, started_at=j.started_at)
    return None


async def _sparkline_sampler(qs: QueueState, dashboard: Dashboard) -> None:
    while True:
        try:
            dashboard.sample_queue(qs.queue.qsize())
        except Exception:  # noqa: BLE001
            log.exception("sparkline sampler crashed; continuing")
        await asyncio.sleep(1.0)


async def _dashboard_refresh(
    qs: QueueState, printer, monitor, app_state, dashboard: Dashboard,
) -> None:
    while True:
        try:
            counters = _aggregate_counters(qs.registry, qs.queue.qsize())
            current = _find_running_job(qs.registry)
            cache = getattr(app_state, "health_cache", {}) or {}
            health = HealthSnapshot(
                battery_pct=cache.get("battery_pct"),
                paper_ok=cache.get("paper_ok"),
            )
            state = LiveState(
                ble_connected=bool(getattr(printer, "is_connected_ble", False)),
                ble_reconnecting=monitor.is_reconnecting,
                ble_reconnect_attempt=monitor.attempt,
                counters=counters,
                current_job=current,
                health=health,
            )
            dashboard.update(state)
        except Exception:  # noqa: BLE001
            log.exception("dashboard refresh crashed; continuing")
        await asyncio.sleep(0.25)


def build_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app):
        dashboard: Dashboard | None = None
        log_file_path: Path | None = None
        dashboard_start_failed = False
        if _dashboard_enabled(settings):
            dashboard = _build_dashboard(settings)
            log_file_path = dashboard.static.log_file_path
            try:
                dashboard.start()
            except Exception as e:  # noqa: BLE001
                dashboard = None
                log_file_path = None
                # Logging isn't configured yet; emit a warning through the
                # logging module (picked up by any pre-existing handler,
                # e.g. pytest's caplog, or Python's lastResort stderr) and
                # also print to stderr for production visibility.
                log.warning("dashboard disabled: %s", e)
                print(f"dashboard disabled: {e}", file=sys.stderr)
                dashboard_start_failed = True

        configure(level=settings.log_level, json=settings.log_json,
                  dashboard=dashboard, log_file_path=log_file_path)

        if dashboard is None and not settings.log_json:
            try:
                from goojprt import __version__ as sdk_version
            except ImportError:
                sdk_version = "unknown"
            print_banner(
                version=__version__,
                sdk_version=sdk_version,
                ble_address=settings.ble_address,
                host=settings.host, port=settings.port,
                log_level=settings.log_level,
                queue_max=settings.queue_max_size,
            )

        # Log the post-dashboard-start fallback warning through logging
        # (will land in file + buffer or stream, as appropriate).
        if dashboard_start_failed:
            log.warning("dashboard disabled (start failed); using streaming logs")

        monitor = ConnectionMonitor()

        def _on_ble_disconnect(_client=None) -> None:
            monitor.signal_disconnect()

        printer = GoojPrtPT210()
        try:
            await printer.connect_ble(settings.ble_address, on_disconnect=_on_ble_disconnect)
            await printer.initialize()
        except Exception as e:  # noqa: BLE001
            if dashboard is not None:
                try:
                    dashboard.stop()
                except Exception:  # noqa: BLE001
                    pass
            log.error("%s BLE connect failed: %s — exiting", glyph("err"), e)
            raise RuntimeError(f"BLE connect failed: {e}") from e
        printer_holder.set_printer(printer)
        ble_log.info("%s connected to %s", glyph("ok"), settings.ble_address)

        qs = QueueState(
            queue=asyncio.Queue(maxsize=settings.queue_max_size),
            max_size=settings.queue_max_size,
        )

        monitor_task = asyncio.create_task(
            run_monitor(monitor, printer, settings, on_disconnect=_on_ble_disconnect)
        )
        worker_task = asyncio.create_task(run_worker(qs, printer, settings, monitor))
        ttl_task = asyncio.create_task(_ttl_sweep(qs, settings.job_ttl_s))
        health_task = asyncio.create_task(_health_refresh(app.state, printer))

        if dashboard is not None:
            sparkline_task = asyncio.create_task(_sparkline_sampler(qs, dashboard))
            dashboard_refresh_task = asyncio.create_task(
                _dashboard_refresh(qs, printer, monitor, app.state, dashboard)
            )
        else:
            sparkline_task = None
            dashboard_refresh_task = None
        app.state.sparkline_task = sparkline_task
        app.state.dashboard_refresh_task = dashboard_refresh_task

        app.state.settings = settings
        app.state.printer = printer
        app.state.queue_state = qs
        app.state.worker_task = worker_task
        app.state.monitor = monitor
        app.state.started_at = time.monotonic()
        app.state.health_cache = {}
        app.state.dashboard = dashboard

        try:
            yield
        finally:
            for t in (sparkline_task, dashboard_refresh_task):
                if t is not None:
                    t.cancel()
            for t in (sparkline_task, dashboard_refresh_task):
                if t is not None:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
            ttl_task.cancel()
            health_task.cancel()
            for t in (ttl_task, health_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            monitor.reconnected.set()
            monitor_task.cancel()
            try:
                await monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            await qs.queue.put(None)
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                worker_task.cancel()
            try:
                await printer.disconnect()
            except Exception:  # noqa: BLE001
                pass
            printer_holder.set_printer(None)
            if dashboard is not None:
                try:
                    dashboard.stop()
                except Exception:  # noqa: BLE001
                    pass
            log.info("server stopped")

    return lifespan
