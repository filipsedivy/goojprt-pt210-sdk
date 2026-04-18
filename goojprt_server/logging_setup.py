"""Logging configuration for goojprt-server.

Two modes:

* **Rich (default)** — a single ``RichHandler`` with second-precision
  timestamps (Rich's ``log_time_format`` does not support milliseconds
  directly; we accept ``%X`` on this path), tracebacks, and per-record
  job-id injection via a ``ContextVar``.
* **JSON** — one JSON object per line on stdout, with millisecond
  timestamps and the same fields.

The Rich path shows seconds; the JSON path shows milliseconds. This is
intentional: stdlib ``logging`` fills ``record.msecs`` but Rich's
``log_time_format`` uses ``strftime`` on a naive ``datetime``; plumbing
millis through Rich is more fragile than it's worth.

Callers never configure the root logger directly; they call
:func:`configure` once at startup.
"""

from __future__ import annotations

import json as _json
import logging
import os
import sys
import time
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

if TYPE_CHECKING:
    from goojprt_server.dashboard import Dashboard

job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


_UNICODE_GLYPHS = {
    "ok": "\u2713", "err": "\u2717", "run": "\u25b6", "dots": "\u22ef", "dot": "\u25cf",
}
_ASCII_GLYPHS = {
    "ok": "OK", "err": "ERR", "run": "->", "dots": "...", "dot": "*",
}


def glyph(name: str) -> str:
    """Return the Unicode glyph, or the ASCII fallback if ``GOOJPRT_NO_UNICODE=1``."""
    if os.environ.get("GOOJPRT_NO_UNICODE") == "1":
        return _ASCII_GLYPHS[name]
    return _UNICODE_GLYPHS[name]


class _JobIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = job_id_var.get()
        record.request_id = request_id_var.get()
        return True


class _RichJobIdFilter(logging.Filter):
    """Rich-path filter that prepends ``[job=<id>]`` to the rendered message.

    ``RichHandler`` short-circuits the formatter in its default
    configuration and renders ``record.getMessage()`` directly, so a
    standard ``Formatter`` is not sufficient to inject the job id into
    the visible output. Mutating ``record.msg`` here is reliable.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        jid = job_id_var.get()
        if jid:
            # Render the original message first so any %-args are
            # interpolated, then prefix the job id. The leading ``\[`` is
            # a Rich-markup escape for a literal ``[`` — without it, the
            # prefix would be mis-parsed as a tag when ``markup=True``.
            try:
                rendered = record.getMessage()
            except Exception:
                rendered = str(record.msg)
            record.msg = f"\\[job={jid}] {rendered}"
            record.args = ()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if getattr(record, "job_id", None):
            payload["job_id"] = record.job_id
        if getattr(record, "request_id", None):
            payload["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            payload["duration_ms"] = record.duration_ms
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return _json.dumps(payload, ensure_ascii=False)


class _FileFormatter(logging.Formatter):
    """File-handler formatter that appends ``[job=<id>]`` and ``[req=<id>]``.

    ``_JobIdFilter`` populates ``record.job_id`` / ``record.request_id``
    from the ContextVars; this formatter surfaces them in the durable
    audit log so ``grep job=<id>`` works on the rotated file.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        jid = getattr(record, "job_id", None)
        rid = getattr(record, "request_id", None)
        suffix = ""
        if jid:
            suffix += f" [job={jid}]"
        if rid:
            suffix += f" [req={rid}]"
        return base + suffix


def configure(
    level: Literal["debug", "info", "warning"],
    json: bool,
    *,
    dashboard: "Dashboard | None" = None,
    log_file_path: Path | None = None,
) -> None:
    """Install the root handler.

    Three modes:
    * ``json=True`` — JSON stream on stdout. ``dashboard`` and
      ``log_file_path`` are ignored (highest-priority branch).
    * ``dashboard`` is not ``None`` — install ``DashboardLogHandler``
      plus a ``RotatingFileHandler`` at ``log_file_path``. No
      ``RichHandler``.
    * Otherwise — install the existing ``RichHandler``.

    Safe to call multiple times; existing root handlers are removed first.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level.upper())

    handlers: list[logging.Handler] = []

    if json:
        h = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(_JsonFormatter())
        handlers.append(h)
    elif dashboard is not None:
        from goojprt_server.dashboard import DashboardLogHandler
        dh = DashboardLogHandler(dashboard)
        handlers.append(dh)
        if log_file_path is not None:
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                str(log_file_path),
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            fh.setFormatter(_FileFormatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
            handlers.append(fh)
    else:
        console = Console(stderr=False, file=sys.stdout)
        rh = RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            omit_repeated_times=False,
            log_time_format="[%X]",
            markup=True,
        )
        rh.addFilter(_RichJobIdFilter())
        handlers.append(rh)

    for h in handlers:
        h.addFilter(_JobIdFilter())
        root.addHandler(h)

    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("bleak").setLevel(logging.WARNING)


def print_banner(
    *,
    version: str,
    sdk_version: str,
    ble_address: str,
    host: str,
    port: int,
    log_level: str,
    queue_max: int,
) -> None:
    """Print the Rich startup panel. No-op if JSON logging is active
    (callers check ``settings.log_json`` before calling)."""
    console = Console()
    body = (
        f"[bold]Version:[/bold]     {version}  (sdk {sdk_version})\n"
        f"[bold]BLE address:[/bold] {ble_address}\n"
        f"[bold]Listening:[/bold]   http://{host}:{port}\n"
        f"[bold]Log level:[/bold]   {log_level.upper()}\n"
        f"[bold]Queue:[/bold]       max {queue_max} jobs"
    )
    console.print(Panel(body, title="GoojPrt PT-210 Print Server", expand=False))
