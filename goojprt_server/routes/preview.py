"""``/api/preview/*`` — render a print job to a PNG without printing it.

Meant for building and checking layouts without wasting paper. The
endpoints take the same bodies as the matching ``/api/print/*`` routes and
run the same dispatch code, but against a throw-away
:class:`~goojprt.transport.preview.PreviewTransport`: they never touch the
job queue, the worker or the real printer, so they also work while the
printer is offline or busy.

Only bitmap jobs can be shown faithfully. Native ESC/POS text
(``bitmap=false``) and QR codes are produced by the printer firmware; in the
PNG they appear as dashed notes, and the ``X-Preview-Native-Commands``
response header counts them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from goojprt import GoojPrtPT210
from goojprt_server.models import (
    PrintEkgRequest,
    PrintGridRequest,
    PrintPdf417Request,
    PrintTextRequest,
)
from goojprt_server.routes.api import ImageForm
from goojprt_server.worker import dispatch_payload

router = APIRouter(prefix="/api/preview", tags=["preview"])

#: Previews that may render at the same time; rendering is CPU-bound.
MAX_CONCURRENT_PREVIEWS = 2

_PNG: dict[int | str, dict[str, Any]] = {200: {"content": {"image/png": {}}, "description": "The rendered job as a PNG image."}}


def _limit(request: Request) -> asyncio.Semaphore:
    """The per-app semaphore bounding concurrent previews (created on first use)."""
    state = request.app.state
    limit = getattr(state, "preview_limit", None)
    if limit is None:
        limit = state.preview_limit = asyncio.Semaphore(MAX_CONCURRENT_PREVIEWS)
    return limit


async def _render(request: Request, job_type: str, payload: dict) -> Response:
    """Run ``payload`` through the normal dispatch against a preview transport."""
    async with _limit(request):
        printer = GoojPrtPT210()
        transport = printer.connect_preview()
        try:
            await dispatch_payload(printer, job_type, payload)
        except (ValueError, OSError) as exc:   # unreadable image, data the encoder rejects, …
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
        png = await asyncio.to_thread(transport.png_bytes)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Preview-Native-Commands": str(transport.native_commands),
            "Cache-Control": "no-store",
        },
    )


@router.post("/text", responses=_PNG)
async def preview_text(body: PrintTextRequest, request: Request) -> Response:
    """Preview text. Use ``bitmap=true``; native text is shown as a note only."""
    return await _render(request, "text", body.model_dump())


@router.post("/pdf417", responses=_PNG)
async def preview_pdf417(body: PrintPdf417Request, request: Request) -> Response:
    return await _render(request, "pdf417", body.model_dump())


@router.post("/ekg", responses=_PNG)
async def preview_ekg(body: PrintEkgRequest, request: Request) -> Response:
    return await _render(request, "ekg", body.model_dump())


@router.post("/grid", responses=_PNG)
async def preview_grid(body: PrintGridRequest, request: Request) -> Response:
    return await _render(request, "grid", body.model_dump())


@router.post("/image", responses=_PNG)
async def preview_image(
    request: Request,
    file: UploadFile = File(...),
    form: ImageForm = Depends(),
) -> Response:
    return await _render(request, "image", await form.payload(file))
