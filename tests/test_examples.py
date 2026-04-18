"""Tests for EKG and Grid models, routes, and dispatch."""
from goojprt_server.models import PrintEkgRequest, PrintGridRequest, GridColumn
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from goojprt_server.app import create_app
from goojprt_server.config import Settings
from goojprt_server.queue import QueueState, JobRegistry
import queue as stdlib_queue


def _make_client():
    qs = QueueState(
        queue=stdlib_queue.Queue(),
        registry=JobRegistry(),
        max_size=50,
    )
    printer = MagicMock()
    printer.is_connected_ble = True
    monitor = MagicMock()
    monitor.is_reconnecting = False
    settings = Settings(ble_address="00:00:00:00:00:00")
    app = create_app(
        settings=settings, queue_state=qs, printer=printer, monitor=monitor, test_mode=True
    )
    app.state.health_cache = {}
    return TestClient(app), qs


def test_api_ekg_enqueues():
    client, qs = _make_client()
    resp = client.post("/api/print/ekg", json={"beats": 3})
    assert resp.status_code == 202
    assert resp.json()["queue_position"] == 1
    job = qs.queue.get_nowait()
    assert job.type == "ekg"
    assert job.payload["beats"] == 3
    assert job.payload["portrait"] is False


def test_api_grid_enqueues():
    client, qs = _make_client()
    cols = [{"width": 50, "align": "left", "text": "X"}]
    resp = client.post("/api/print/grid", json={"columns": cols})
    assert resp.status_code == 202
    job = qs.queue.get_nowait()
    assert job.type == "grid"
    assert job.payload["columns"] == cols


def test_ekg_model_defaults():
    m = PrintEkgRequest()
    assert m.beats == 4
    assert m.height_px == 160
    assert m.line_width == 2
    assert m.grid is True
    assert m.amplitude == 0.82
    assert m.portrait is False
    assert m.px_per_beat == 240
    assert m.feed_after == 0


def test_ekg_model_validation():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrintEkgRequest(beats=0)
    with pytest.raises(ValidationError):
        PrintEkgRequest(amplitude=1.5)


def test_grid_model_defaults():
    m = PrintGridRequest(columns=[{"width": 50, "align": "left", "text": "A"}])
    assert m.font_size == 22
    assert m.dither is False
    assert m.feed_after == 0


def test_grid_model_requires_columns():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrintGridRequest()


def test_grid_column_validation():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrintGridRequest(columns=[{"align": "left", "text": "A"}])  # missing width
    with pytest.raises(ValidationError):
        PrintGridRequest(columns=[{"width": 50, "align": "bad", "text": "A"}])  # invalid align


import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_dispatch_ekg():
    from goojprt_server.worker import dispatch
    from goojprt_server.queue import Job
    import time

    printer = MagicMock()
    printer.print_ekg = AsyncMock()
    job = Job(
        id="test-ekg",
        type="ekg",
        payload={"beats": 3, "height_px": 120, "line_width": 2,
                 "grid": True, "amplitude": 0.82, "portrait": False,
                 "px_per_beat": 240},
        status="running",
        created_at=time.monotonic(),
        started_at=None, finished_at=None, error=None,
    )
    await dispatch(printer, job)
    printer.print_ekg.assert_called_once_with(
        beats=3, height_px=120, line_width=2, grid=True,
        amplitude=0.82, portrait=False, px_per_beat=240,
    )


@pytest.mark.asyncio
async def test_dispatch_grid():
    from goojprt_server.worker import dispatch
    from goojprt_server.queue import Job
    import time

    printer = MagicMock()
    printer.print_grid = AsyncMock()
    cols = [{"width": 50, "align": "left", "text": "A"}]
    job = Job(
        id="test-grid",
        type="grid",
        payload={"columns": cols, "font_size": 22, "dither": False},
        status="running",
        created_at=time.monotonic(),
        started_at=None, finished_at=None, error=None,
    )
    await dispatch(printer, job)
    printer.print_grid.assert_called_once_with(
        columns=cols, font_size=22, dither=False,
    )


def test_main_page_has_examples_link():
    client, _ = _make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/examples" in resp.content


def test_examples_page_has_back_link():
    client, _ = _make_client()
    resp = client.get("/examples")
    assert b'href="/"' in resp.content


def test_examples_get():
    client, _ = _make_client()
    resp = client.get("/examples")
    assert resp.status_code == 200
    assert b"EKG" in resp.content
    assert b"Grid" in resp.content


def test_examples_post_ekg_redirects():
    client, qs = _make_client()
    resp = client.post(
        "/examples",
        data={"_type": "ekg", "beats": "4", "height_px": "160",
              "line_width": "2", "amplitude": "0.82",
              "px_per_beat": "240"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=ok" in resp.headers["location"]
    job = qs.queue.get_nowait()
    assert job.type == "ekg"


def test_examples_post_ekg_grid_checkbox():
    """grid=True when checkbox present, grid=False when absent."""
    client, qs = _make_client()

    # With grid checkbox checked (form sends "grid": "on")
    resp = client.post(
        "/examples",
        data={"_type": "ekg", "beats": "2", "height_px": "160",
              "line_width": "2", "amplitude": "0.82", "px_per_beat": "240",
              "grid": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    job = qs.queue.get_nowait()
    assert job.payload["grid"] is True

    # Without grid checkbox (unchecked — form sends nothing for grid)
    resp = client.post(
        "/examples",
        data={"_type": "ekg", "beats": "2", "height_px": "160",
              "line_width": "2", "amplitude": "0.82", "px_per_beat": "240"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    job = qs.queue.get_nowait()
    assert job.payload["grid"] is False


def test_examples_post_grid_redirects():
    client, qs = _make_client()
    resp = client.post(
        "/examples",
        data={
            "_type": "grid",
            "col_width[]": ["40", "30", "30"],
            "col_text[]": ["Item", "Qty", "Price"],
            "col_align[]": ["left", "right", "right"],
            "font_size": "22",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    job = qs.queue.get_nowait()
    assert job.type == "grid"
    assert job.payload["columns"] == [
        {"width": 40, "align": "left", "text": "Item"},
        {"width": 30, "align": "right", "text": "Qty"},
        {"width": 30, "align": "right", "text": "Price"},
    ]
