"""Server behaviour that keeps print jobs intact and the event loop responsive."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from goojprt_server import lifespan, worker
from goojprt_server.queue import Job, JobRegistry, QueueState


def _job(status="queued", started=False) -> Job:
    now = time.monotonic()
    return Job(
        id="abc12345", type="text", payload={}, status=status, created_at=now,
        started_at=now if started else None, finished_at=None, error=None,
    )


def _state(*jobs: Job, queued: int = 0) -> SimpleNamespace:
    qs = QueueState(queue=asyncio.Queue(maxsize=10), registry=JobRegistry(), max_size=10)
    for job in jobs:
        qs.registry.add(job)
    for _ in range(queued):
        qs.queue.put_nowait(_job())
    return SimpleNamespace(queue_state=qs)


# ── _printer_busy ─────────────────────────────────────────────────────────────

def test_idle_printer_is_not_busy():
    assert lifespan._printer_busy(_state()) is False


def test_printer_is_busy_while_a_job_is_queued():
    assert lifespan._printer_busy(_state(queued=1)) is True


def test_printer_is_busy_while_a_job_runs():
    assert lifespan._printer_busy(_state(_job("running", started=True))) is True


def test_finished_jobs_do_not_make_the_printer_busy():
    done = _job("done", started=True)
    done.finished_at = time.monotonic()
    assert lifespan._printer_busy(_state(done)) is False


def test_printer_is_not_busy_before_the_queue_exists():
    assert lifespan._printer_busy(SimpleNamespace()) is False


# ── _health_refresh ───────────────────────────────────────────────────────────

class _Printer:
    def __init__(self) -> None:
        self.is_connected_ble = True
        self.queries = 0

    async def query_full_info(self, timeout: float = 1.5) -> dict:
        self.queries += 1
        return {"ble_battery": {"level_pct": 55}, "escpos_status": {"paper": {"ok": True}}}


async def _one_refresh(monkeypatch, app_state, printer) -> None:
    """Run exactly one iteration of ``_health_refresh``."""

    async def stop_after_first_iteration(_delay):
        raise asyncio.CancelledError

    # Replace only the module's reference to asyncio, not asyncio itself.
    monkeypatch.setattr(lifespan, "asyncio", SimpleNamespace(sleep=stop_after_first_iteration))
    with pytest.raises(asyncio.CancelledError):
        await lifespan._health_refresh(app_state, printer)


async def test_health_refresh_queries_an_idle_printer(monkeypatch):
    state, printer = _state(), _Printer()
    state.health_cache = {}
    await _one_refresh(monkeypatch, state, printer)
    assert printer.queries == 1
    assert state.health_cache == {"battery_pct": 55, "paper_ok": True}


async def test_health_refresh_leaves_a_busy_printer_alone(monkeypatch):
    state, printer = _state(_job("running", started=True)), _Printer()
    state.health_cache = {"battery_pct": 90}
    await _one_refresh(monkeypatch, state, printer)
    assert printer.queries == 0
    assert state.health_cache == {"battery_pct": 90}  # previous values stay


async def test_health_refresh_skips_while_jobs_are_waiting(monkeypatch):
    state, printer = _state(queued=2), _Printer()
    state.health_cache = {}
    await _one_refresh(monkeypatch, state, printer)
    assert printer.queries == 0


# ── image preparation runs off the event loop ────────────────────────────────

async def test_image_jobs_are_prepared_in_a_worker_thread(monkeypatch):
    seen: list[threading.Thread] = []

    def fake_prepare(_payload):
        seen.append(threading.current_thread())
        return "prepared-image"

    printed: list[object] = []

    class Printer:
        async def print_image(self, image):
            printed.append(image)

    monkeypatch.setattr(worker, "_prepare_image", fake_prepare)
    job = _job()
    job.type = "image"
    job.payload = {"image_b64": ""}
    await worker.dispatch(Printer(), job)

    assert printed == ["prepared-image"]
    assert seen and seen[0] is not threading.main_thread()
