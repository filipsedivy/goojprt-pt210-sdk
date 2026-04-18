import asyncio

import pytest


async def _wait_for_status(client, job_id, target, timeout=1.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        r = await client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json()["status"] == target:
            return r.json()
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {target} within {timeout}s")


async def test_print_text_accepted_and_completes(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "hello"})
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["queue_position"] >= 0

    job = await _wait_for_status(client, body["job_id"], "done")
    assert job["type"] == "text"
    assert job["duration_ms"] is not None

    methods = [c[0] for c in fake_printer.calls]
    assert "print_text" in methods


async def test_print_text_bitmap_routes_to_print_text_image(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "ě", "bitmap": True})
    assert r.status_code == 202
    await _wait_for_status(client, r.json()["job_id"], "done")
    methods = [c[0] for c in fake_printer.calls]
    assert "print_text_image" in methods


async def test_print_qr_accepted(client, fake_printer):
    r = await client.post("/api/print/qr", json={"data": "https://ex.test"})
    assert r.status_code == 202
    await _wait_for_status(client, r.json()["job_id"], "done")
    assert any(c[0] == "print_qr" for c in fake_printer.calls)


async def test_print_pdf417_accepted(client, fake_printer):
    r = await client.post("/api/print/pdf417", json={"data": "1234567890"})
    assert r.status_code == 202
    await _wait_for_status(client, r.json()["job_id"], "done")
    assert any(c[0] == "print_pdf417" for c in fake_printer.calls)


async def test_feed_accepted(client, fake_printer):
    r = await client.post("/api/feed", json={"lines": 4})
    assert r.status_code == 202
    await _wait_for_status(client, r.json()["job_id"], "done")
    assert ("feed", {"lines": 4}) in fake_printer.calls


async def test_unknown_job_returns_404(client):
    r = await client.get("/api/jobs/nosuchjob")
    assert r.status_code == 404
    assert r.json() == {"error": "job not found"}


async def test_list_jobs_returns_recent_newest_first(client, fake_printer):
    r1 = await client.post("/api/print/text", json={"text": "first"})
    j1 = r1.json()["job_id"]
    await _wait_for_status(client, j1, "done")
    r2 = await client.post("/api/feed", json={"lines": 1})
    j2 = r2.json()["job_id"]
    await _wait_for_status(client, j2, "done")

    listing = await client.get("/api/jobs?limit=10")
    assert listing.status_code == 200
    items = listing.json()
    assert isinstance(items, list)
    assert len(items) >= 2
    # Newest first.
    assert items[0]["id"] == j2
    assert items[1]["id"] == j1
    # Shape matches single-job response.
    assert set(items[0].keys()) >= {"id", "type", "status", "created_at", "duration_ms", "error"}


async def test_list_jobs_default_limit(client, fake_printer):
    r = await client.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_feed_after_triggers_feed(client, fake_printer):
    r = await client.post("/api/print/text",
                          json={"text": "hi", "feed_after": 2})
    assert r.status_code == 202
    await _wait_for_status(client, r.json()["job_id"], "done")
    # Both print_text and a subsequent feed(2) should have happened.
    calls = [c for c in fake_printer.calls if c[0] in ("print_text", "feed")]
    assert ("feed", {"lines": 2}) in calls
