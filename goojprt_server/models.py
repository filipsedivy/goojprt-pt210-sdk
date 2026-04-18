"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PrintTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    align: Literal["left", "center", "right"] = "left"
    bold: bool = False
    underline: bool = False
    size: Literal["normal", "double_width", "double_height", "double_both"] = "normal"
    bitmap: bool = False
    font_size: int = Field(default=24, ge=8, le=96)
    encoding: str = "gb2312"
    feed_after: int = Field(default=0, ge=0, le=20)


class PrintQrRequest(BaseModel):
    data: str = Field(..., min_length=1, max_length=2000)
    size: int = Field(default=6, ge=1, le=16)
    align: Literal["left", "center", "right"] = "center"
    error_correction: Literal[0, 1, 2, 3] = 1
    feed_after: int = Field(default=0, ge=0, le=20)


class PrintPdf417Request(BaseModel):
    data: str = Field(..., min_length=1, max_length=2000)
    align: Literal["left", "center", "right"] = "center"
    scale: int = Field(default=2, ge=1, le=6)
    columns: int = Field(default=5, ge=1, le=30)
    row_height: int = Field(default=5, ge=2, le=12)
    feed_after: int = Field(default=0, ge=0, le=20)


class FeedRequest(BaseModel):
    lines: int = Field(default=3, ge=1, le=20)


class JobAcceptedResponse(BaseModel):
    job_id: str
    queue_position: int


class JobResponse(BaseModel):
    id: str
    type: str
    status: Literal["queued", "running", "done", "failed"]
    created_at: float
    duration_ms: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    connected: bool
    queue_size: int
    queue_max: int
    worker_alive: bool
    uptime_s: float
    battery_pct: int | None = None
    paper_ok: bool | None = None
    reconnecting: bool = False
    reconnect_attempt: int = 0


class VersionResponse(BaseModel):
    sdk: str
    server: str


class PrintEkgRequest(BaseModel):
    beats: int = Field(default=4, ge=1, le=20)
    height_px: int = Field(default=160, ge=60, le=400)
    line_width: int = Field(default=2, ge=1, le=4)
    grid: bool = True
    amplitude: float = Field(default=0.82, ge=0.1, le=1.0)
    portrait: bool = False
    px_per_beat: int = Field(default=240, ge=60, le=600)
    feed_after: int = Field(default=0, ge=0, le=20)


class GridColumn(BaseModel):
    width: int = Field(..., ge=1, le=384)
    align: Literal["left", "center", "right"] = "left"
    text: str


class PrintGridRequest(BaseModel):
    columns: list[GridColumn] = Field(..., min_length=1)
    font_size: int = Field(default=22, ge=8, le=64)
    dither: bool = False
    feed_after: int = Field(default=0, ge=0, le=20)
