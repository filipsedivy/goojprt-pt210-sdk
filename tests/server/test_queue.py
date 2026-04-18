import asyncio
import time

import pytest

from goojprt_server.queue import Job, JobRegistry, make_job_id


async def test_registry_add_and_get():
    reg = JobRegistry()
    job = Job(
        id=make_job_id(), type="text", payload={"text": "hi"},
        status="queued", created_at=time.monotonic(),
        started_at=None, finished_at=None, error=None,
    )
    reg.add(job)
    assert reg.get(job.id) is job
    assert reg.get("missing") is None


async def test_registry_recent_sorted_desc():
    reg = JobRegistry()
    ids = []
    for _ in range(3):
        j = Job(
            id=make_job_id(), type="text", payload={},
            status="done", created_at=time.monotonic(),
            started_at=None, finished_at=None, error=None,
        )
        reg.add(j)
        ids.append(j.id)
        await asyncio.sleep(0.001)
    recent = reg.recent(limit=5)
    assert [j.id for j in recent] == list(reversed(ids))


async def test_registry_sweep_removes_old_finished_jobs():
    reg = JobRegistry()
    fresh = Job(id=make_job_id(), type="text", payload={},
                status="done", created_at=0, started_at=0,
                finished_at=time.monotonic(), error=None)
    stale = Job(id=make_job_id(), type="text", payload={},
                status="done", created_at=0, started_at=0,
                finished_at=time.monotonic() - 10_000, error=None)
    running = Job(id=make_job_id(), type="text", payload={},
                  status="running", created_at=0, started_at=0,
                  finished_at=None, error=None)
    reg.add(fresh); reg.add(stale); reg.add(running)
    removed = reg.sweep(ttl_s=3600)
    assert removed == 1
    assert reg.get(stale.id) is None
    assert reg.get(fresh.id) is fresh
    assert reg.get(running.id) is running
