from __future__ import annotations

import asyncio
import pytest

from goojprt_server.connection_monitor import ConnectionMonitor, run_monitor
from goojprt_server.config import Settings
from tests.server.fake_printer import FakePrinter


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    return Settings(reconnect_interval_s=0.02, reconnect_log_interval_s=999.0)


@pytest.mark.asyncio
async def test_signal_disconnect_sets_reconnecting():
    monitor = ConnectionMonitor()
    assert monitor.is_reconnecting is False
    monitor.signal_disconnect()
    assert monitor.is_reconnecting is True


@pytest.mark.asyncio
async def test_reconnects_on_second_attempt(settings):
    """Printer fails first connect, succeeds second — monitor should reconnect."""
    fake = FakePrinter()
    await fake.connect_ble("AA:BB:CC:DD:EE:FF")
    await fake.initialize()
    fake.fail_n_times = 1  # first connect_ble call will fail

    monitor = ConnectionMonitor()
    monitor.signal_disconnect()

    task = asyncio.create_task(run_monitor(monitor, fake, settings))
    try:
        await asyncio.wait_for(monitor.reconnected.wait(), timeout=1.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert monitor.is_reconnecting is False
    assert monitor.attempt == 0
    connect_calls = [c for c, _ in fake.calls if c == "connect_ble"]
    assert len(connect_calls) >= 2  # initial + at least one reconnect


@pytest.mark.asyncio
async def test_reconnected_event_set_after_success(settings):
    fake = FakePrinter()
    await fake.connect_ble("AA:BB:CC:DD:EE:FF")
    await fake.initialize()

    monitor = ConnectionMonitor()
    monitor.signal_disconnect()

    task = asyncio.create_task(run_monitor(monitor, fake, settings))
    try:
        await asyncio.wait_for(monitor.reconnected.wait(), timeout=1.0)
        assert monitor.reconnected.is_set()
        assert monitor.is_reconnecting is False
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_signal_disconnect_idempotent():
    """Calling signal_disconnect twice must not crash or reset attempt counter."""
    monitor = ConnectionMonitor()
    monitor.signal_disconnect()
    monitor.attempt = 3
    monitor.signal_disconnect()  # second call while already reconnecting
    assert monitor.is_reconnecting is True
    assert monitor.attempt == 3  # not reset by second signal


@pytest.mark.asyncio
async def test_signal_disconnect_clears_reconnected_on_double_call(settings):
    """reconnected must stay cleared if signal_disconnect fires twice."""
    fake = FakePrinter()
    await fake.connect_ble("AA:BB:CC:DD:EE:FF")
    await fake.initialize()

    monitor = ConnectionMonitor()
    monitor.signal_disconnect()   # first call
    monitor.signal_disconnect()   # second call — reconnected must still be cleared
    assert not monitor.reconnected.is_set()
    assert monitor.is_reconnecting is True
