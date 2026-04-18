import pytest

from goojprt_server.connection_monitor import ConnectionMonitor


async def test_health_reports_connected_and_queue(client, fake_printer):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["queue_size"] == 0
    assert body["queue_max"] == 3
    assert body["worker_alive"] is True
    assert body["uptime_s"] >= 0.0
    assert "battery_pct" in body
    assert "paper_ok" in body
    assert body["reconnecting"] is False
    assert body["reconnect_attempt"] == 0


async def test_health_reconnecting_fields(client, fake_printer, monitor):
    monitor.is_reconnecting = True
    monitor.attempt = 4

    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["reconnecting"] is True
    assert body["reconnect_attempt"] == 4
