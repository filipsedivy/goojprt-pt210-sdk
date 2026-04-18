from __future__ import annotations

import asyncio

import pytest


async def _wait(client, job_id, target, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        r = await client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json()["status"] == target:
            return r.json()
        await asyncio.sleep(0.01)
    raise AssertionError(f"{job_id} never reached {target!r}")


@pytest.mark.asyncio
async def test_worker_recovers_after_single_ble_failure(client, fake_printer, monitor):
    """After a BleakError the monitor reconnects; next job succeeds."""
    fake_printer.fail_n_times = 1

    r1 = await client.post("/api/print/text", json={"text": "first"})
    assert r1.status_code == 202
    j1 = await _wait(client, r1.json()["job_id"], "failed")
    assert "BLE" in (j1["error"] or "")

    # Wait for monitor to reconnect (reconnect_interval_s=0.02 in test settings)
    await asyncio.wait_for(monitor.reconnected.wait(), timeout=1.0)

    r2 = await client.post("/api/print/text", json={"text": "second"})
    assert r2.status_code == 202
    j2 = await _wait(client, r2.json()["job_id"], "done")

    methods = [c for c, _ in fake_printer.calls]
    assert "print_text:FAIL" in methods
    assert methods.count("connect_ble") >= 2
    assert "initialize" in methods[methods.index("print_text:FAIL"):]


@pytest.mark.asyncio
async def test_worker_job_times_out_when_reconnect_too_slow(
    client, fake_printer, monitor, settings
):
    """Jobs fail with timeout error when reconnect takes longer than reconnect_job_wait_s."""
    # Override job wait timeout to be very short
    settings.reconnect_job_wait_s = 0.05
    settings.reconnect_interval_s = 10.0  # make reconnect take "forever"

    fake_printer.fail_n_times = 999  # block all reconnect attempts
    monitor.signal_disconnect()  # put monitor into reconnecting state

    r = await client.post("/api/print/text", json={"text": "hello"})
    assert r.status_code == 202
    j = await _wait(client, r.json()["job_id"], "failed", timeout=2.0)
    assert "reconnect timed out" in (j["error"] or "").lower()
