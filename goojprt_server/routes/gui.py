"""Minimal server-rendered GUI. No JS; meta-refresh every 2s."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from goojprt_server.models import (
    FeedRequest,
    PrintEkgRequest,
    PrintGridRequest,
    PrintPdf417Request,
    PrintQrRequest,
    PrintTextRequest,
)
from goojprt_server.routes.api import _enqueue

router = APIRouter()


def _build_form_payload(job_type: str, form: dict) -> dict:
    """Validate form data via the matching Pydantic model."""
    if job_type == "ekg":
        return PrintEkgRequest(
            beats=int(form.get("beats") or 4),
            height_px=int(form.get("height_px") or 160),
            line_width=int(form.get("line_width") or 2),
            grid="grid" in form,
            amplitude=float(form.get("amplitude") or 0.82),
            portrait="portrait" in form,
            px_per_beat=int(form.get("px_per_beat") or 240),
            feed_after=int(form.get("feed_after") or 0),
        ).model_dump()
    if job_type == "grid":
        widths = form.getlist("col_width[]") if hasattr(form, "getlist") else [form.get("col_width[]")]
        texts = form.getlist("col_text[]") if hasattr(form, "getlist") else [form.get("col_text[]")]
        aligns = form.getlist("col_align[]") if hasattr(form, "getlist") else [form.get("col_align[]")]
        columns = [
            {"width": int(w), "align": a, "text": t}
            for w, a, t in zip(widths, aligns, texts)
        ]
        return PrintGridRequest(
            columns=columns,
            font_size=int(form.get("font_size") or 22),
            dither=bool(form.get("dither")),
            feed_after=int(form.get("feed_after") or 0),
        ).model_dump()
    if job_type == "text":
        return PrintTextRequest(
            text=form.get("text", ""),
            align=form.get("align", "left"),
            bold=bool(form.get("bold")),
            underline=bool(form.get("underline")),
            size=form.get("size", "normal"),
            bitmap=bool(form.get("bitmap")),
            feed_after=int(form.get("feed_after") or 0),
        ).model_dump()
    if job_type == "qr":
        return PrintQrRequest(
            data=form["data"],
            size=int(form.get("size") or 6),
            align=form.get("align", "center"),
        ).model_dump()
    if job_type == "pdf417":
        return PrintPdf417Request(
            data=form["data"],
            align=form.get("align", "center"),
            columns=int(form.get("columns") or 5),
            scale=int(form.get("scale") or 2),
            row_height=int(form.get("row_height") or 5),
        ).model_dump()
    if job_type == "feed":
        return FeedRequest(lines=int(form.get("lines") or 3)).model_dump()
    raise HTTPException(status_code=400, detail="unknown _type")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    st = request.app.state
    qs = st.queue_state
    cache: dict = getattr(st, "health_cache", {}) or {}
    return st.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "connected": st.printer.is_connected_ble,
            "queue_size": qs.queue.qsize(),
            "queue_max": qs.max_size,
            "battery_pct": cache.get("battery_pct"),
            "paper_ok": cache.get("paper_ok"),
            "recent": [
                {
                    "id": j.id, "type": j.type, "status": j.status,
                    "duration_ms": j.duration_ms(),
                }
                for j in qs.registry.recent(limit=20)
            ],
            "flash": request.query_params.get("flash"),
            "flash_msg": ("job queued" if request.query_params.get("flash") == "ok"
                          else None),
        },
    )


@router.post("/")
async def submit(request: Request) -> RedirectResponse:
    form = dict(await request.form())
    job_type = form.pop("_type", None)
    if job_type not in {"text", "qr", "pdf417", "feed"}:
        raise HTTPException(status_code=400, detail="unknown _type")
    payload = _build_form_payload(job_type, form)
    result = _enqueue(request.app.state.queue_state, job_type, payload)
    return RedirectResponse(
        url=f"/?job={result.job_id}&flash=ok",
        status_code=303,
    )


@router.get("/examples", response_class=HTMLResponse)
async def examples_index(request: Request) -> HTMLResponse:
    st = request.app.state
    return st.templates.TemplateResponse(
        request=request,
        name="examples.html",
        context={
            "connected": st.printer.is_connected_ble,
            "queue_size": st.queue_state.queue.qsize(),
            "queue_max": st.queue_state.max_size,
            "flash": request.query_params.get("flash"),
            "flash_msg": ("job queued" if request.query_params.get("flash") == "ok"
                          else None),
        },
    )


@router.post("/examples")
async def examples_submit(request: Request) -> RedirectResponse:
    raw_form = await request.form()
    form = dict(raw_form)
    # Extract multi-value fields before plain dict squashes them
    multi = {
        "col_width[]": raw_form.getlist("col_width[]"),
        "col_text[]": raw_form.getlist("col_text[]"),
        "col_align[]": raw_form.getlist("col_align[]"),
    }

    class _MultiForm(dict):
        def getlist(self, key):
            return multi.get(key, [])

    merged = _MultiForm(form)

    job_type = merged.pop("_type", None)
    if job_type not in {"ekg", "grid"}:
        raise HTTPException(status_code=400, detail="unknown _type")
    payload = _build_form_payload(job_type, merged)
    result = _enqueue(request.app.state.queue_state, job_type, payload)
    return RedirectResponse(
        url=f"/examples?job={result.job_id}&flash=ok",
        status_code=303,
    )
