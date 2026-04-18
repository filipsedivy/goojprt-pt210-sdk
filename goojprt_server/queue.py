"""In-memory job queue + registry for goojprt-server.

The queue is an ``asyncio.Queue`` bounded by ``Settings.queue_max_size``.
The registry is a dict keyed by job id; a background sweep task removes
entries whose ``finished_at`` is older than ``Settings.job_ttl_s``.

Concurrency: reads/writes to the registry dict happen from the HTTP
handlers (enqueue), the worker (status transitions) and the sweep task.
Python's dict is safe for single-key atomic ops, which is all we use.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobType = Literal["text", "qr", "pdf417", "feed"]
JobStatus = Literal["queued", "running", "done", "failed"]


def make_job_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Job:
    id: str
    type: JobType
    payload: dict[str, Any]
    status: JobStatus
    created_at: float
    started_at: float | None
    finished_at: float | None
    error: str | None

    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at) * 1000)


class JobRegistry:
    """In-memory dictionary of jobs, keyed by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def add(self, job: Job) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def iter_jobs(self):
        """Iterate over all jobs. Order is insertion order (asyncio-safe)."""
        return self._jobs.values()

    def recent(self, limit: int = 20) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    def sweep(self, ttl_s: float) -> int:
        """Remove finished jobs whose ``finished_at`` is older than ``ttl_s`` ago.
        Returns the number of removed entries.
        """
        cutoff = time.monotonic() - ttl_s
        to_remove = [
            jid for jid, j in self._jobs.items()
            if j.finished_at is not None and j.finished_at < cutoff
        ]
        for jid in to_remove:
            del self._jobs[jid]
        return len(to_remove)


@dataclass
class QueueState:
    """Bundle the queue + registry so lifespan can put one thing on app.state."""
    queue: asyncio.Queue[Job | None]
    registry: JobRegistry = field(default_factory=JobRegistry)
    max_size: int = 100
