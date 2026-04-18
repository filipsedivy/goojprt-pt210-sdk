"""FastAPI app factory.

Two ways to construct:
* ``create_app()`` — production: reads ``Settings`` from env and installs
  the real lifespan (BLE connect, background tasks).
* ``create_app(settings=..., queue_state=..., printer=..., test_mode=True)``
  — tests: skip lifespan, wire a pre-built fake printer and an empty
  queue directly onto ``app.state``.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pathlib import Path

from goojprt_server import printer_holder
from goojprt_server.config import Settings
from goojprt_server.lifespan import build_lifespan
from goojprt_server.middleware.access_log import AccessLogMiddleware
from goojprt_server.queue import QueueState
from goojprt_server.routes import api as api_routes
from goojprt_server.routes import gui as gui_routes
from goojprt_server.routes import health as health_routes

_PKG_ROOT = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_PKG_ROOT / "templates"))


def create_app(
    *,
    settings: Optional[Settings] = None,
    queue_state: Optional[QueueState] = None,
    printer=None,
    monitor=None,
    test_mode: bool = False,
) -> FastAPI:
    settings = settings or Settings()  # reads env

    if test_mode:
        app = FastAPI(title="GoojPrt PT-210 Print Server", lifespan=None)
        # Tests set state themselves; still set sensible defaults.
        app.state.started_at = time.monotonic()
        app.state.settings = settings
        app.state.health_cache = {}
        if queue_state is not None:
            app.state.queue_state = queue_state
        if printer is not None:
            app.state.printer = printer
            printer_holder.set_printer(printer)
        if monitor is not None:
            app.state.monitor = monitor
    else:
        app = FastAPI(
            title="GoojPrt PT-210 Print Server",
            lifespan=build_lifespan(settings),
        )
        app.state.settings = settings

    # Middleware must be added before routes for ASGI middleware order.
    app.add_middleware(AccessLogMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_routes.router)
    app.include_router(health_routes.router)
    app.include_router(gui_routes.router)
    app.mount("/static", StaticFiles(directory=str(_PKG_ROOT / "static")), name="static")
    # Make templates available to gui routes.
    app.state.templates = _TEMPLATES
    return app
