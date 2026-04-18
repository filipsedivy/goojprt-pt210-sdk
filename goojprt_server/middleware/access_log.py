"""Pure-ASGI access log — logs once per request after the response."""

from __future__ import annotations

import logging
import time
import uuid

from goojprt_server.logging_setup import request_id_var

log = logging.getLogger("goojprt_server.http")

# Requests we log at DEBUG only (polled by the GUI every 2 s).
_DEBUG_PATHS = {"/api/health"}


class AccessLogMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        client = scope.get("client") or ("", 0)
        req_id = uuid.uuid4().hex[:8]
        token = request_id_var.set(req_id)
        start = time.monotonic()
        status_holder: list[int] = [500]

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder[0] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", req_id.encode()))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            status = status_holder[0]
            level = logging.DEBUG if path in _DEBUG_PATHS else logging.INFO
            colour = "green" if status < 400 else "yellow" if status < 500 else "red"
            log.log(
                level,
                "[%s]%s[/%s] %s %s -> %d (%dms) %s",
                colour, status, colour, method, path, status, duration_ms, client[0],
            )
            request_id_var.reset(token)
