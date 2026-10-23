"""Server: native text jobs, the preview of them and the profile at startup."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from PIL import Image

from goojprt.profile import TextProfile, save_profile
from goojprt_server.app import create_app
from goojprt_server.cli import build_parser, settings_from_args
from goojprt_server.config import Settings
from goojprt_server.lifespan import build_lifespan
from tests.server.fake_printer import FakePrinter


async def _wait_done(client, job_id):
    import asyncio
    for _ in range(100):
        job = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in ("done", "failed"):
            return job
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish")


def _calls(fake, name):
    return [c[1] for c in fake.calls if c[0] == name]


async def test_text_jobs_leave_the_encoding_to_the_printer_by_default(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "Příliš"})
    assert (await _wait_done(client, r.json()["job_id"]))["status"] == "done"
    call, = _calls(fake_printer, "print_text")
    assert call["encoding"] is None


async def test_an_explicit_encoding_is_passed_on(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "x", "encoding": "cp852"})
    await _wait_done(client, r.json()["job_id"])
    assert _calls(fake_printer, "print_text")[0]["encoding"] == "cp852"


async def test_auto_jobs_use_print_text_auto(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "Cena 5 €", "auto": True, "bold": True,
                                                   "align": "center", "font_size": 30})
    assert (await _wait_done(client, r.json()["job_id"]))["status"] == "done"
    assert _calls(fake_printer, "print_text") == []
    call, = _calls(fake_printer, "print_text_auto")
    assert call["text"] == "Cena 5 €" and call["bold"] is True and call["font_size"] == 30


async def test_bitmap_wins_over_auto(client, fake_printer):
    r = await client.post("/api/print/text", json={"text": "x", "auto": True, "bitmap": True})
    await _wait_done(client, r.json()["job_id"])
    assert _calls(fake_printer, "print_text_auto") == []
    assert len(_calls(fake_printer, "print_text_image")) == 1


async def test_auto_defaults_to_off(client):
    r = await client.post("/api/print/text", json={"text": "x"})
    assert r.status_code == 202


async def test_preview_of_auto_text_without_a_profile_is_a_bitmap_for_czech(client):
    r = await client.post("/api/preview/text", json={"text": "Příliš", "auto": True})
    assert r.status_code == 200 and r.headers["x-preview-native-commands"] == "0"
    assert Image.open(io.BytesIO(r.content)).height > 20


async def test_preview_of_auto_text_is_native_for_ascii(client):
    r = await client.post("/api/preview/text", json={"text": "plain", "auto": True})
    assert r.headers["x-preview-native-commands"] == "1"


# ── profile at startup ───────────────────────────────────────────────────────

async def _start(monkeypatch, **settings_kwargs) -> FakePrinter:
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3, **settings_kwargs)
    fake = FakePrinter()
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        async with build_lifespan(settings)(app):
            pass
    return fake


async def test_a_profile_is_applied_right_after_initialisation(monkeypatch, tmp_path):
    file = tmp_path / "p.toml"
    save_profile(TextProfile(18, "cp852"), file)
    fake = await _start(monkeypatch, profile=file)
    names = [c[0] for c in fake.calls]
    assert names.index("connect_ble") < names.index("initialize") < names.index("apply_profile")
    assert _calls(fake, "apply_profile") == [{"profile": TextProfile(18, "cp852")}]


async def test_no_profile_leaves_the_printer_alone(monkeypatch, tmp_path):
    file = tmp_path / "p.toml"
    save_profile(TextProfile(18, "cp852"), file)
    fake = await _start(monkeypatch, profile=file, no_profile=True)
    assert _calls(fake, "apply_profile") == []


async def test_a_missing_profile_file_is_not_an_error(monkeypatch, tmp_path):
    fake = await _start(monkeypatch, profile=tmp_path / "nope.toml")
    assert _calls(fake, "apply_profile") == []


async def test_an_invalid_profile_stops_the_server_before_it_connects(monkeypatch, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[text]\ncode_page = 999\nencoding = \"cp852\"\n")
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    settings = Settings(queue_max_size=3, profile=bad)
    fake = FakePrinter()
    with patch("goojprt_server.lifespan.GoojPrtPT210", return_value=fake):
        app = create_app(settings=settings)
        with pytest.raises(RuntimeError, match="native text profile.*code_page"):
            async with build_lifespan(settings)(app):
                pytest.fail("the server must not start")
    assert _calls(fake, "connect_ble") == []


def test_cli_flags_reach_the_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOJPRT_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")
    ns = build_parser().parse_args(["--profile", str(tmp_path / "p.toml"), "--no-profile"])
    s = settings_from_args(ns)
    assert s.profile == tmp_path / "p.toml" and s.no_profile is True
    s = settings_from_args(build_parser().parse_args([]))
    assert s.no_profile is False
