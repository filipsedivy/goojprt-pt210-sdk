"""Tests for GoojPrtPT210 guards, Chinese-mode control, status decoding and the probe."""
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from goojprt import commands, raster
from goojprt.enums import CodePage
from goojprt.printer import GoojPrtPT210
from goojprt.transport.ble import BleTransport


def _ble_printer() -> GoojPrtPT210:
    p = GoojPrtPT210()
    p._ble = MagicMock(spec=BleTransport)
    p._ble.is_connected = True
    p._ble.write = AsyncMock()
    p._ble.write_raster_strip = AsyncMock()
    return p


def _written(p: GoojPrtPT210) -> list[bytes]:
    return [c.args[0] for c in p._ble.write.call_args_list]


# ── not connected ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("call", [
    lambda p: p.initialize(),
    lambda p: p.print_text("x"),
    lambda p: p.feed(1),
    lambda p: p.print_qr("x"),
    lambda p: p.set_chinese_mode(False),
    lambda p: p.print_image(Image.new("1", (384, 8), 1)),
])
async def test_ble_methods_explain_how_to_connect(call):
    with pytest.raises(RuntimeError, match=r"connect_ble\(\)"):
        await call(GoojPrtPT210())


def test_spp_methods_explain_how_to_connect():
    with pytest.raises(RuntimeError, match=r"connect_spp\(\)"):
        GoojPrtPT210().print_text_spp("x")


# ── connect_ble passes tunables to the transport ─────────────────────────────

@pytest.mark.asyncio
async def test_connect_ble_forwards_chunk_settings_to_new_transport():
    mock_ble = MagicMock(spec=BleTransport)
    mock_ble.connect = AsyncMock()
    with patch("goojprt.printer.BleTransport", return_value=mock_ble) as factory:
        await GoojPrtPT210().connect_ble("AA:BB", chunk_size=100, chunk_delay=0.01)
    factory.assert_called_once_with(on_disconnect=None, chunk_size=100, chunk_delay=0.01)


@pytest.mark.asyncio
async def test_connect_ble_omits_unset_chunk_settings():
    mock_ble = MagicMock(spec=BleTransport)
    mock_ble.connect = AsyncMock()
    with patch("goojprt.printer.BleTransport", return_value=mock_ble) as factory:
        await GoojPrtPT210().connect_ble("AA:BB")
    factory.assert_called_once_with(on_disconnect=None)


# ── Chinese mode ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_chinese_mode_off_sends_fs_dot():
    p = _ble_printer()
    await p.set_chinese_mode(False)
    p._ble.write.assert_awaited_once_with(b"\x1c\x2e")


@pytest.mark.asyncio
async def test_set_chinese_mode_on_sends_fs_ampersand():
    p = _ble_printer()
    await p.set_chinese_mode(True)
    p._ble.write.assert_awaited_once_with(b"\x1c\x26")


# ── rendering does not block the event loop ──────────────────────────────────

@pytest.mark.asyncio
async def test_text_image_is_rendered_in_a_worker_thread():
    p = _ble_printer()
    threads: list[threading.Thread] = []

    def fake_render(*_args, **_kwargs):
        threads.append(threading.current_thread())
        return Image.new("1", (384, 8), 1)

    with patch("goojprt.printer.rendering.render_text_image", side_effect=fake_render):
        await p.print_text_image("hello")

    assert threads and threads[0] is not threading.main_thread()
    assert p._ble.write_raster_strip.called


@pytest.mark.asyncio
async def test_rasterising_happens_in_a_worker_thread():
    p = _ble_printer()
    threads: list[threading.Thread] = []
    real = raster.image_to_raster_strips

    def spy(image, strip_height=24):
        threads.append(threading.current_thread())
        return real(image, strip_height=strip_height)

    with patch("goojprt.printer.raster.image_to_raster_strips", side_effect=spy):
        await p.print_image(Image.new("1", (384, 48), 1))

    assert threads and threads[0] is not threading.main_thread()
    assert p._ble.write_raster_strip.await_count == 2


# ── decoded status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_full_info_reports_decoded_flags():
    p = _ble_printer()
    p._ble.has_notify = True
    p._ble.clear_notify_buffer = MagicMock()
    p._ble.read_gatt = AsyncMock(side_effect=Exception("no gatt"))
    # Answers in query order: printer, offline cause, error cause, paper sensor.
    p._ble.read_notify = AsyncMock(side_effect=[b"\x00", b"\x04", b"\x00", b"\x0c", b"", b"", b""])

    info = await p.query_full_info(timeout=0.1)

    assert info["escpos_status"]["printer"]["ok"] is True
    assert info["escpos_status"]["offline"]["flags"]["cover_open"] is True
    assert info["escpos_status"]["offline"]["ok"] is False
    paper = info["escpos_status"]["paper"]
    assert paper == {"raw": 0x0C, "ok": False, "flags": {"paper_low": True, "paper_end": False}}
    sent = _written(p)
    assert sent[:4] == [commands.status_request(n) for n in (1, 2, 3, 4)]


# ── probe ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_prints_each_page_with_and_without_fs_dot():
    p = _ble_printer()
    await p.probe_charsets(test_string="abc", pages=[CodePage.PC852, CodePage.WPC1250_STD])

    sent = _written(p)
    fs_dot = commands.chinese_mode(False)
    assert sent.count(fs_dot) == 2  # once per page, only in the second variant
    for cp in (CodePage.PC852, CodePage.WPC1250_STD):
        select = commands.charset(cp)
        assert sent.count(select) == 2
        first, second = [i for i, b in enumerate(sent) if b == select]
        assert fs_dot not in sent[first - 1:first]          # default variant: no FS . right before
        assert sent[second - 1] == fs_dot                    # FS . precedes ESC t in the second


@pytest.mark.asyncio
async def test_probe_resets_the_printer_before_every_variant():
    p = _ble_printer()
    await p.probe_charsets(test_string="abc", pages=[CodePage.PC437])
    sent = _written(p)
    for i, b in enumerate(sent):
        if b == commands.charset(CodePage.PC437):
            # ESC @ (or FS . right after ESC @) comes directly before the code page switch
            assert commands.init() in sent[max(0, i - 2):i]


@pytest.mark.asyncio
async def test_probe_can_skip_the_fs_dot_variant():
    p = _ble_printer()
    await p.probe_charsets(test_string="abc", pages=[CodePage.PC437], try_chinese_mode_off=False)
    assert commands.chinese_mode(False) not in _written(p)


@pytest.mark.asyncio
async def test_probe_default_pages_include_both_cp1250_slots():
    p = _ble_printer()
    await p.probe_charsets(test_string="abc")
    sent = _written(p)
    assert commands.charset(CodePage.WPC1250) in sent       # ESC t 16
    assert commands.charset(CodePage.WPC1250_STD) in sent   # ESC t 45


# ── print jobs stay intact next to concurrent status queries ─────────────────

class _UartClient:
    """Fake bleak client that records the byte stream the printer would see."""

    is_connected = True

    def __init__(self) -> None:
        self.stream = bytearray()

    async def write_gatt_char(self, _char, chunk, response):
        self.stream.extend(chunk)
        await asyncio.sleep(0)  # let other tasks run between chunks


def _split_stream(stream: bytes, strips: list[bytes], query: bytes) -> list[str]:
    """Parse ``stream`` into whole strips and whole queries; fail on anything else."""
    parts, pos, next_strip = [], 0, 0
    while pos < len(stream):
        if stream.startswith(query, pos):
            parts.append("query")
            pos += len(query)
        elif next_strip < len(strips) and stream.startswith(strips[next_strip], pos):
            parts.append("strip")
            pos += len(strips[next_strip])
            next_strip += 1
        else:
            raise AssertionError(f"stream corrupted at byte {pos}")
    assert next_strip == len(strips), "some strips never arrived"
    return parts


async def _print_while_polling_status(use_lock: bool) -> list[str]:
    client = _UartClient()
    transport = BleTransport(chunk_delay=0.0)
    transport._client = client
    transport._write_char = "w"
    if not use_lock:
        class _NoLock:
            async def __aenter__(self): return None
            async def __aexit__(self, *exc): return False
        transport._write_lock = _NoLock()
    printer = GoojPrtPT210()
    printer._ble = transport

    image = Image.new("1", (384, 96), 0)  # four 24-row strips
    strips = raster.image_to_raster_strips(image)
    query = commands.status_request(4)

    job_done = asyncio.Event()

    async def print_job():
        try:
            await printer.print_image(image)
        finally:
            job_done.set()

    async def poll_status():
        # Keep querying until the job has finished, so the two always overlap.
        while not job_done.is_set():
            await transport.write(query)
            await asyncio.sleep(0)

    await asyncio.gather(print_job(), poll_status())
    return _split_stream(bytes(client.stream), strips, query)


@pytest.mark.asyncio
async def test_status_queries_never_land_inside_a_raster_strip():
    parts = await _print_while_polling_status(use_lock=True)
    assert parts.count("strip") == 4
    assert parts.count("query") >= 1  # the polling really ran alongside the job


@pytest.mark.asyncio
async def test_the_check_itself_detects_interleaving_without_the_lock():
    # Negative control: proves the test above would catch a missing lock.
    with pytest.raises(AssertionError, match="corrupted"):
        await _print_while_polling_status(use_lock=False)
