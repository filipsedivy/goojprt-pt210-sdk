"""POST /api/preview/*: PNG previews that never touch the queue or the printer."""
import asyncio
import io

import pytest
from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png(w=20, h=20, color=(128, 128, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _decode(response) -> Image.Image:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)
    return Image.open(io.BytesIO(response.content))


def _printer_calls(fake_printer) -> list[str]:
    return [c[0] for c in fake_printer.calls if c[0] not in ("connect_ble", "initialize")]


async def test_text_preview_is_a_png_of_the_paper_width(client):
    r = await client.post("/api/preview/text", json={"text": "Příliš žluťoučký kůň", "bitmap": True})
    img = _decode(r)
    assert img.width == 384 and img.height > 10
    assert r.headers["x-preview-native-commands"] == "0"
    assert r.headers["cache-control"] == "no-store"


async def test_native_text_is_reported_in_a_header(client):
    r = await client.post("/api/preview/text", json={"text": "native", "bitmap": False})
    _decode(r)
    assert r.headers["x-preview-native-commands"] == "1"


async def test_feed_after_adds_blank_paper(client):
    plain = _decode(await client.post("/api/preview/text", json={"text": "x", "bitmap": True}))
    fed = _decode(await client.post("/api/preview/text",
                                    json={"text": "x", "bitmap": True, "feed_after": 3}))
    assert fed.height == plain.height + 3 * 30
    assert fed.size[0] == 384


@pytest.mark.parametrize("path, body", [
    ("pdf417", {"data": "GoojPrt-PT210"}),
    ("ekg", {"beats": 2, "height_px": 80}),
    ("grid", {"columns": [{"width": 40, "text": "Káva"}, {"width": 60, "align": "right", "text": "35 Kč"}]}),
])
async def test_bitmap_jobs_preview(client, path, body):
    img = _decode(await client.post(f"/api/preview/{path}", json=body))
    assert img.width == 384


async def test_preview_never_uses_the_queue_or_the_printer(client, fake_printer):
    before = _printer_calls(fake_printer)
    await client.post("/api/preview/text", json={"text": "x", "bitmap": True})
    await client.post("/api/preview/ekg", json={})
    assert _printer_calls(fake_printer) == before == []
    assert (await client.get("/api/jobs")).json() == []
    assert (await client.get("/api/health")).json()["queue_size"] == 0


async def test_preview_works_while_the_printer_is_offline(client, fake_printer):
    fake_printer._connected = False
    _decode(await client.post("/api/preview/text", json={"text": "x", "bitmap": True}))


async def test_image_preview_shows_the_fitted_picture(client):
    r = await client.post(
        "/api/preview/image",
        files={"file": ("big.png", _png(1000, 500, (0, 0, 0)), "image/png")},
    )
    img = _decode(r)
    assert (img.width, img.height) == (384, 192)
    assert img.convert("L").getextrema()[0] == 0


async def test_image_preview_shows_what_a_cropping_job_would_print(client):
    # fit=none keeps 1000 px, and the print path cuts it to the print head width.
    r = await client.post(
        "/api/preview/image",
        files={"file": ("big.png", _png(1000, 500), "image/png")},
        data={"fit": "none"},
    )
    assert _decode(r).width == 384


async def test_unreadable_image_is_a_422_with_a_message(client):
    r = await client.post("/api/preview/image", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 422
    assert "error" in r.json()["detail"]


async def test_oversized_upload_is_rejected(client):
    big = b"\0" * (10 * 1024 * 1024 + 1)
    r = await client.post("/api/preview/image", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 413


async def test_validation_errors_are_422(client):
    assert (await client.post("/api/preview/text", json={"text": ""})).status_code == 422
    assert (await client.post("/api/preview/image", data={})).status_code == 422
    r = await client.post("/api/preview/image", files={"file": ("x.png", _png(), "image/png")},
                          data={"fit": "stretch"})
    assert r.status_code == 422


async def test_concurrent_previews_are_bounded(client, monkeypatch):
    from goojprt_server.routes import preview

    running = peak = 0

    async def slow_dispatch(printer, job_type, payload):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1

    monkeypatch.setattr(preview, "dispatch_payload", slow_dispatch)
    responses = await asyncio.gather(*[
        client.post("/api/preview/text", json={"text": "x", "bitmap": True}) for _ in range(6)
    ])
    assert all(r.status_code == 200 for r in responses)
    assert peak == preview.MAX_CONCURRENT_PREVIEWS
