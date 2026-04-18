"""/api/health — never blocks on BLE, reads only cached state."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from goojprt_server.models import HealthResponse

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    st = request.app.state
    cache: dict = getattr(st, "health_cache", {}) or {}
    monitor = getattr(st, "monitor", None)
    return HealthResponse(
        connected=st.printer.is_connected_ble,
        queue_size=st.queue_state.queue.qsize(),
        queue_max=st.queue_state.max_size,
        worker_alive=not st.worker_task.done(),
        uptime_s=time.monotonic() - st.started_at,
        battery_pct=cache.get("battery_pct"),
        paper_ok=cache.get("paper_ok"),
        reconnecting=monitor.is_reconnecting if monitor else False,
        reconnect_attempt=monitor.attempt if monitor else 0,
    )
