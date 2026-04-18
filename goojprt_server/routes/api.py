"""JSON API: /api/print/*, /api/jobs/*, /api/version."""

from __future__ import annotations

import base64
import logging
import time

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from goojprt_server import __version__ as server_version
from goojprt_server.models import (
    FeedRequest,
    JobAcceptedResponse,
    JobResponse,
    PrintPdf417Request,
    PrintQrRequest,
    PrintTextRequest,
    VersionResponse,
)
from goojprt_server.queue import Job, QueueState, make_job_id

router = APIRouter(prefix="/api")
log = logging.getLogger("goojprt_server.queue")


def _enqueue(qs: QueueState, job_type: str, payload: dict) -> JobAcceptedResponse:
    if qs.queue.qsize() >= qs.max_size:
        log.warning("queue full (%d/%d), rejecting request",
                    qs.queue.qsize(), qs.max_size)
        raise HTTPException(
            status_code=503,
            detail={"error": "queue full", "retry_after_s": 2},
        )
    job = Job(
        id=make_job_id(),
        type=job_type,   # type: ignore[arg-type]
        payload=payload,
        status="queued",
        created_at=time.monotonic(),
        started_at=None,
        finished_at=None,
        error=None,
    )
    qs.registry.add(job)
    qs.queue.put_nowait(job)
    log.debug("enqueued job=%s type=%s qsize=%d", job.id, job_type, qs.queue.qsize())
    return JobAcceptedResponse(job_id=job.id, queue_position=qs.queue.qsize())


def _qs(request: Request) -> QueueState:
    return request.app.state.queue_state


@router.post("/print/text", status_code=202, response_model=JobAcceptedResponse)
async def print_text(body: PrintTextRequest, request: Request) -> JobAcceptedResponse:
    return _enqueue(_qs(request), "text", body.model_dump())


@router.post("/print/qr", status_code=202, response_model=JobAcceptedResponse)
async def print_qr(body: PrintQrRequest, request: Request) -> JobAcceptedResponse:
    return _enqueue(_qs(request), "qr", body.model_dump())


@router.post("/print/pdf417", status_code=202, response_model=JobAcceptedResponse)
async def print_pdf417(body: PrintPdf417Request, request: Request) -> JobAcceptedResponse:
    return _enqueue(_qs(request), "pdf417", body.model_dump())


@router.post("/feed", status_code=202, response_model=JobAcceptedResponse)
async def feed(body: FeedRequest, request: Request) -> JobAcceptedResponse:
    return _enqueue(_qs(request), "feed", body.model_dump())


@router.get("/jobs")
async def list_jobs(request: Request, limit: int = 20) -> list[JobResponse]:
    """Recent jobs, newest first, capped at ``limit`` (default 20)."""
    limit = max(1, min(limit, 200))
    return [
        JobResponse(
            id=j.id,
            type=j.type,
            status=j.status,
            created_at=j.created_at,
            duration_ms=j.duration_ms(),
            error=j.error,
        )
        for j in _qs(request).registry.recent(limit=limit)
    ]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    job = _qs(request).registry.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        created_at=job.created_at,
        duration_ms=job.duration_ms(),
        error=job.error,
    )


@router.post("/print/image", status_code=202, response_model=JobAcceptedResponse)
async def print_image(
    request: Request,
    file: UploadFile = File(...),
    rotate: int = Form(0),
    crop_x: float = Form(0.0),
    crop_y: float = Form(0.0),
    crop_w: float = Form(1.0),
    crop_h: float = Form(1.0),
    brightness: float = Form(1.0),
    contrast: float = Form(1.0),
    threshold: int = Form(128),
    dither: bool = Form(True),
    scale: float = Form(1.0),
    align: str = Form("center"),
    feed_after: int = Form(0),
) -> JobAcceptedResponse:
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error": "image too large (max 10 MB)"})
    payload = {
        "image_b64": base64.b64encode(raw).decode(),
        "rotate": rotate,
        "crop": (crop_x, crop_y, crop_w, crop_h),
        "brightness": brightness,
        "contrast": contrast,
        "threshold": threshold,
        "dither": dither,
        "scale": scale,
        "align": align,
        "feed_after": feed_after,
    }
    return _enqueue(_qs(request), "image", payload)


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    try:
        from goojprt import __version__ as sdk_version  # type: ignore[attr-defined]
    except ImportError:
        sdk_version = "unknown"
    return VersionResponse(sdk=sdk_version, server=server_version)
