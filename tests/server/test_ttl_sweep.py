import time


async def test_sweep_removes_stale_finished_jobs(test_app, fake_printer):
    # Run a job to completion, then backdate its finished_at and sweep.
    qs = test_app.state.queue_state
    from goojprt_server.queue import Job, make_job_id
    j = Job(id=make_job_id(), type="text", payload={},
            status="done", created_at=0.0, started_at=0.0,
            finished_at=time.monotonic() - 7200, error=None)
    qs.registry.add(j)
    removed = qs.registry.sweep(ttl_s=3600)
    assert removed == 1
    assert qs.registry.get(j.id) is None
