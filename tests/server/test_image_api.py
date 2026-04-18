"""Integration tests for POST /api/print/image."""
import asyncio
import io

import pytest
from PIL import Image


def _png_bytes(w=20, h=20, color=(128, 128, 128)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


async def _wait_done(client, job_id, timeout=2.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        r = await client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json()["status"] in ("done", "failed"):
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} timed out")


async def test_print_image_accepted_and_completes(client, fake_printer):
    png = _png_bytes()
    r = await client.post(
        "/api/print/image",
        files={"file": ("test.png", png, "image/png")},
        data={"rotate": "0", "scale": "1.0", "dither": "true"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    job = await _wait_done(client, job_id)
    assert job["status"] == "done"
    assert job["type"] == "image"
    assert any(c[0] == "print_image" for c in fake_printer.calls)


async def test_print_image_with_feed_after(client, fake_printer):
    png = _png_bytes()
    r = await client.post(
        "/api/print/image",
        files={"file": ("test.png", png, "image/png")},
        data={"feed_after": "3"},
    )
    assert r.status_code == 202
    job = await _wait_done(client, r.json()["job_id"])
    assert job["status"] == "done"
    calls = [c[0] for c in fake_printer.calls]
    assert "print_image" in calls
    assert "feed" in calls


async def test_print_image_missing_file_returns_422(client):
    r = await client.post("/api/print/image", data={"rotate": "0"})
    assert r.status_code == 422


async def test_print_image_job_appears_in_listing(client, fake_printer):
    png = _png_bytes()
    r = await client.post(
        "/api/print/image",
        files={"file": ("img.png", png, "image/png")},
    )
    job_id = r.json()["job_id"]
    await _wait_done(client, job_id)

    listing = await client.get("/api/jobs?limit=10")
    ids = [j["id"] for j in listing.json()]
    assert job_id in ids
