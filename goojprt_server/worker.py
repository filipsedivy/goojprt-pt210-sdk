"""Queue consumer + BLE dispatcher.

The worker is the **only** task that touches
:class:`goojprt.GoojPrtPT210`. Serial access is guaranteed by running a
single worker per process. Every log line emitted inside ``run_worker``
carries the current job id via :data:`goojprt_server.logging_setup.job_id_var`.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import TYPE_CHECKING

from bleak.exc import BleakError

from goojprt import Align, TextSize
from goojprt_server.logging_setup import glyph, job_id_var
from goojprt_server.queue import Job, QueueState

if TYPE_CHECKING:
    from goojprt_server.config import Settings
    from goojprt_server.connection_monitor import ConnectionMonitor

log = logging.getLogger("goojprt_server.worker")
ble_log = logging.getLogger("goojprt_server.ble")


_ALIGN = {"left": Align.LEFT, "center": Align.CENTER, "right": Align.RIGHT}
_SIZE = {
    "normal": TextSize.NORMAL,
    "double_width": TextSize.DOUBLE_WIDTH,
    "double_height": TextSize.DOUBLE_HEIGHT,
    "double_both": TextSize.DOUBLE_BOTH,
}


async def dispatch(printer, job: Job) -> None:
    """Translate a job's payload into SDK calls. No business logic."""
    p = job.payload
    if job.type == "text":
        if p.get("bitmap"):
            await printer.print_text_image(
                text=p["text"],
                font_size=p.get("font_size", 24),
                align=_ALIGN[p.get("align", "left")],
            )
        else:
            await printer.print_text(
                text=p["text"],
                align=_ALIGN[p.get("align", "left")],
                bold=p.get("bold", False),
                underline=p.get("underline", False),
                size=_SIZE[p.get("size", "normal")],
                encoding=p.get("encoding", "gb2312"),
            )
        if p.get("feed_after", 0) > 0:
            await printer.feed(lines=p["feed_after"])

    elif job.type == "qr":
        await printer.print_qr(
            data=p["data"],
            size=p.get("size", 6),
            align=_ALIGN[p.get("align", "center")],
            error_correction=p.get("error_correction", 1),
        )
        if p.get("feed_after", 0) > 0:
            await printer.feed(lines=p["feed_after"])

    elif job.type == "pdf417":
        await printer.print_pdf417(
            data=p["data"],
            align=_ALIGN[p.get("align", "center")],
            scale=p.get("scale", 2),
            columns=p.get("columns", 5),
            row_height=p.get("row_height", 5),
        )
        if p.get("feed_after", 0) > 0:
            await printer.feed(lines=p["feed_after"])

    elif job.type == "feed":
        await printer.feed(lines=p.get("lines", 3))

    elif job.type == "image":
        from PIL import Image as PILImage
        from goojprt.rendering.image_print import prepare_image

        raw = base64.b64decode(p["image_b64"])
        src = PILImage.open(io.BytesIO(raw))
        prepared = prepare_image(
            src,
            rotate=p.get("rotate", 0),
            crop=tuple(p["crop"]) if p.get("crop") else None,
            brightness=p.get("brightness", 1.0),
            contrast=p.get("contrast", 1.0),
            threshold=p.get("threshold", 128),
            dither=p.get("dither", True),
            scale=p.get("scale", 1.0),
            align=p.get("align", "center"),
        )
        await printer.print_image(prepared)
        if p.get("feed_after", 0) > 0:
            await printer.feed(lines=p["feed_after"])

    elif job.type == "ekg":
        await printer.print_ekg(
            beats=p.get("beats", 4),
            height_px=p.get("height_px", 160),
            line_width=p.get("line_width", 2),
            grid=p.get("grid", True),
            amplitude=p.get("amplitude", 0.82),
            portrait=p.get("portrait", False),
            px_per_beat=p.get("px_per_beat", 240),
        )

    elif job.type == "grid":
        await printer.print_grid(
            columns=p["columns"],
            font_size=p.get("font_size", 22),
            dither=p.get("dither", False),
        )

    else:
        raise ValueError(f"unknown job type: {job.type}")


async def run_worker(
    qs: QueueState,
    printer,
    settings: "Settings",
    monitor: "ConnectionMonitor",
) -> None:
    """Consume jobs until the shutdown sentinel (``None``) arrives."""
    log.info("worker started")
    while True:
        job = await qs.queue.get()
        if job is None:
            qs.queue.task_done()
            log.info("worker stopping")
            return

        token = job_id_var.set(job.id)
        job.status = "running"
        job.started_at = time.monotonic()
        log.info("%s job=%s type=%s", glyph("run"), job.id, job.type)

        try:
            if monitor.is_reconnecting:
                log.info("%s job=%s waiting for reconnect", glyph("dots"), job.id)
                try:
                    await asyncio.wait_for(
                        monitor.reconnected.wait(),
                        timeout=settings.reconnect_job_wait_s,
                    )
                except asyncio.TimeoutError:
                    job.finished_at = time.monotonic()
                    job.status = "failed"
                    job.error = "printer disconnected — reconnect timed out"
                    log.error(
                        "%s job=%s reconnect timed out after %.0fs",
                        glyph("err"), job.id, settings.reconnect_job_wait_s,
                    )
                    continue

            await dispatch(printer, job)
            job.status = "done"
            job.finished_at = time.monotonic()
            log.info("%s job=%s done in %dms",
                     glyph("ok"), job.id, job.duration_ms() or 0)
        except BleakError as e:
            job.finished_at = time.monotonic()
            job.status = "failed"
            job.error = f"BLE error: {e}"
            log.error("%s job=%s BLE error: %s", glyph("err"), job.id, e)
            monitor.signal_disconnect()
        except Exception as e:  # noqa: BLE001
            job.finished_at = time.monotonic()
            job.status = "failed"
            job.error = str(e)
            log.exception("%s job=%s failed", glyph("err"), job.id)
        finally:
            qs.queue.task_done()
            job_id_var.reset(token)
