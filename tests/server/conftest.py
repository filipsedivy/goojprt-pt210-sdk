"""Shared pytest fixtures for goojprt_server tests."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import pytest
import pytest_asyncio

from goojprt_server import printer_holder
from goojprt_server.config import Settings
from goojprt_server.app import create_app
from goojprt_server.connection_monitor import ConnectionMonitor, run_monitor
from goojprt_server.queue import QueueState
from goojprt_server.worker import run_worker
from tests.server.fake_printer import FakePrinter


@pytest_asyncio.fixture
async def settings(monkeypatch) -> Settings:
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    return Settings(
        queue_max_size=3,
        job_ttl_s=60,
        reconnect_interval_s=0.02,
        reconnect_job_wait_s=60.0,
        reconnect_log_interval_s=999.0,
    )


@pytest_asyncio.fixture
async def fake_printer() -> FakePrinter:
    p = FakePrinter()
    await p.connect_ble("AA:BB:CC:DD:EE:FF")
    await p.initialize()
    return p


@pytest_asyncio.fixture
async def monitor() -> ConnectionMonitor:
    return ConnectionMonitor()


@pytest_asyncio.fixture
async def test_app(settings, fake_printer, monitor):
    printer_holder.set_printer(fake_printer)  # type: ignore[arg-type]
    qs = QueueState(queue=asyncio.Queue(maxsize=settings.queue_max_size),
                    max_size=settings.queue_max_size)
    app = create_app(settings=settings, queue_state=qs,
                     printer=fake_printer, monitor=monitor, test_mode=True)
    monitor_task = asyncio.create_task(run_monitor(monitor, fake_printer, settings))
    worker = asyncio.create_task(run_worker(qs, fake_printer, settings, monitor))
    app.state.worker_task = worker
    app.state.queue_state = qs
    app.state.printer = fake_printer
    app.state.monitor = monitor
    try:
        yield app
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await qs.queue.put(None)
        try:
            await asyncio.wait_for(worker, timeout=1.0)
        except asyncio.TimeoutError:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        finally:
            printer_holder.set_printer(None)


@pytest_asyncio.fixture
async def client(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        yield c
