"""PreviewTransport: faithfulness of the rendered preview and handling of native commands."""
import random
from pathlib import Path

import pytest
from PIL import Image

from goojprt import commands, raster
from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align
from goojprt.printer import GoojPrtPT210
from goojprt.raster import _normalize_to_paper_width, raster_to_image
from goojprt.rendering import render_ekg, render_grid, render_pdf417, render_text_image
from goojprt.transport.preview import PreviewTransport, _describe_native

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _noise(width: int, height: int, seed: int = 3, mode: str = "1") -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("L", (width, height))
    img.putdata([rnd.choice((0, 255)) for _ in range(width * height)])
    return img.convert(mode)


def _facade() -> tuple[GoojPrtPT210, PreviewTransport]:
    printer = GoojPrtPT210()
    return printer, printer.connect_preview()


# ── raster_to_image ───────────────────────────────────────────────────────────

class TestRasterToImage:
    @pytest.mark.parametrize("width, height", [(384, 1), (384, 24), (384, 25), (100, 7), (500, 9)])
    def test_round_trip_of_a_whole_raster(self, width, height):
        img = _noise(width, height)
        decoded = raster_to_image(raster.image_to_raster(img))
        assert decoded.mode == "1"
        assert decoded.tobytes() == _normalize_to_paper_width(img).tobytes()

    def test_strips_stacked_equal_the_whole_image(self):
        img = _noise(384, 61)
        strips = [raster_to_image(s) for s in raster.image_to_raster_strips(img)]
        assert sum(s.height for s in strips) == 61
        assert b"".join(s.tobytes() for s in strips) == _normalize_to_paper_width(img).tobytes()

    def test_trailing_bytes_are_ignored(self):
        payload = raster.image_to_raster(_noise(384, 2)) + b"extra"
        assert raster_to_image(payload).height == 2

    @pytest.mark.parametrize("payload", [b"", b"\x1d\x76", b"\x1b\x40" + bytes(10),
                                         b"\x1d\x76\x30\x01" + bytes(10)])
    def test_rejects_something_that_is_not_a_raster(self, payload):
        with pytest.raises(ValueError, match="GS v 0"):
            raster_to_image(payload)

    def test_rejects_truncated_pixel_data(self):
        payload = raster.image_to_raster(_noise(384, 4))[:-1]
        with pytest.raises(ValueError, match="truncated"):
            raster_to_image(payload)


# ── fidelity through the facade ───────────────────────────────────────────────

class TestFidelity:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("height", [1, 24, 25, 97])
    async def test_print_image_preview_equals_the_normalised_image(self, height):
        printer, preview = _facade()
        img = _noise(384, height)
        await printer.print_image(img)
        assert preview.image().tobytes() == _normalize_to_paper_width(img).tobytes()

    @pytest.mark.asyncio
    async def test_narrow_and_wide_sources_are_shown_as_they_would_print(self):
        for width in (100, 500):
            printer, preview = _facade()
            img = _noise(width, 30, mode="RGB")
            await printer.print_image(img)
            expected = _normalize_to_paper_width(img.convert("1"))
            assert preview.image().tobytes() == expected.tobytes()
            assert preview.image().width == PAPER_WIDTH_PX

    @pytest.mark.asyncio
    async def test_print_text_image_preview_equals_the_renderer_output(self):
        printer, preview = _facade()
        text = "Příliš žluťoučký kůň\núpěl ďábelské ódy"
        await printer.print_text_image(text, font_size=24)
        expected = render_text_image(
            text, font_size=24, line_spacing=6, padding=8, align=Align.LEFT,
            supersample=3, dither=True, threshold=140,
        )
        assert preview.image().tobytes() == expected.tobytes()

    @pytest.mark.asyncio
    async def test_print_grid_ekg_and_pdf417_match_their_renderers(self):
        columns = [{"width": 40, "align": "left", "text": "Káva"},
                   {"width": 60, "align": "right", "text": "35 Kč"}]
        printer, preview = _facade()
        await printer.print_grid(columns)
        assert preview.image().tobytes() == render_grid(columns).tobytes()

        printer, preview = _facade()
        await printer.print_ekg(beats=2, height_px=80)
        assert preview.image().tobytes() == render_ekg(beats=2, height_px=80).tobytes()

        printer, preview = _facade()
        await printer.print_pdf417("GoojPrt-PT210")
        expected = raster.pad_image_to_paper_width(render_pdf417("GoojPrt-PT210"), Align.CENTER)
        assert preview.image().tobytes() == _normalize_to_paper_width(expected).tobytes()


# ── ordering, feeds and native commands ──────────────────────────────────────

class TestComposition:
    @pytest.mark.asyncio
    async def test_parts_are_stacked_in_print_order(self):
        printer, preview = _facade()
        first, second = _noise(384, 30, seed=1), _noise(384, 20, seed=2)
        await printer.print_image(first)
        await printer.feed(2)
        await printer.print_text("native line")
        await printer.print_image(second)

        image = preview.image()
        note_y = 30 + 2 * PreviewTransport.FEED_LINE_PX
        assert image.height == note_y + PreviewTransport.NOTE_HEIGHT_PX + 20
        assert image.crop((0, 0, 384, 30)).tobytes() == first.tobytes()
        assert image.crop((0, image.height - 20, 384, image.height)).tobytes() == second.tobytes()
        # the feed is blank paper
        assert image.crop((0, 30, 384, note_y)).convert("L").getextrema() == (255, 255)
        # the note is a dashed band: black pixels on its top border
        assert image.getpixel((0, note_y)) == 0

    @pytest.mark.asyncio
    async def test_initialise_is_invisible(self):
        printer, preview = _facade()
        await printer.initialize()
        assert preview.height == 1 and preview.native_commands == 0

    @pytest.mark.asyncio
    async def test_native_text_is_counted_and_described_without_command_bytes(self):
        printer, preview = _facade()
        await printer.print_text("Hello", bold=True)
        assert preview.native_commands == 1
        assert preview._parts == ["Hello"]          # no stray 'aE-!' from the escape sequences

    @pytest.mark.asyncio
    async def test_qr_shows_its_payload(self):
        printer, preview = _facade()
        await printer.print_qr("https://example.com")
        assert preview.native_commands == 1
        assert preview._parts == ["QR https://example.com"]

    def test_empty_job_is_a_white_one_pixel_image(self):
        image = PreviewTransport().image()
        assert image.size == (PAPER_WIDTH_PX, 1)
        assert image.convert("L").getextrema() == (255, 255)

    @pytest.mark.asyncio
    async def test_a_wider_raster_widens_the_canvas(self):
        transport = PreviewTransport()
        await transport.write_raster_strip(raster_payload := b"\x1d\x76\x30\x00\x40\x00\x02\x00" + bytes(128))
        assert len(raster_payload) == 8 + 128
        assert transport.image().size == (512, 2)

    @pytest.mark.asyncio
    async def test_feed_of_zero_lines_adds_nothing(self):
        transport = PreviewTransport()
        await transport.write(commands.feed(0))
        assert transport.height == 1


class TestDescribeNative:
    @pytest.mark.parametrize("data, expected", [
        (commands.build_text_block("Hello"), "Hello"),
        (commands.build_text_block("A\nB"), "A | B"),
        (commands.build_text_block("Příliš", encoding="cp1250"), "P??li?"),   # ř, í, š are code-page bytes
        (commands.build_qr_block("data-1"), "QR data-1"),
        (commands.charset(commands.CodePage.PC852) + b"x", "x"),
        (commands.energy() + b"y", "y"),
        (commands.chinese_mode(False) + b"z", "z"),
        (b"\x1b", "1 bytes"),
        (b"\x00\x01", "2 bytes"),
    ])
    def test_known_sequences(self, data, expected):
        assert _describe_native(data) == expected

    def test_long_text_is_shortened(self):
        label = _describe_native(b"x" * 500)
        assert len(label) == 60 and label.endswith("...")

    def test_arbitrary_bytes_never_raise_or_hang(self):
        rnd = random.Random(7)
        for _ in range(2000):
            data = bytes(rnd.randrange(256) for _ in range(rnd.randrange(0, 40)))
            assert isinstance(_describe_native(data), str)

    def test_truncated_commands_never_raise(self):
        for cmd in (b"\x1d\x28\x6b", b"\x1d\x28\x6b\xff\xff", b"\x1d\x28\x6b\x05\x00\x31",
                    b"\x1d\x56", b"\x1b\x37\x01", b"\x1c"):
            assert isinstance(_describe_native(cmd), str)


# ── transport contract ────────────────────────────────────────────────────────

class TestTransport:
    @pytest.mark.asyncio
    async def test_it_is_connected_from_the_start_and_reconnectable(self):
        t = PreviewTransport()
        assert t.is_connected
        await t.disconnect()
        assert not t.is_connected
        await t.connect()
        assert t.is_connected

    @pytest.mark.asyncio
    async def test_writes_after_disconnect_raise_but_the_recording_stays(self):
        t = PreviewTransport()
        await t.write_raster_strip(raster.image_to_raster(_noise(384, 3)))
        await t.disconnect()
        with pytest.raises(RuntimeError, match="not connected"):
            await t.write(b"x")
        with pytest.raises(RuntimeError, match="not connected"):
            await t.write_raster_strip(raster.image_to_raster(_noise(384, 3)))
        assert t.image().height == 3

    @pytest.mark.asyncio
    async def test_a_malformed_strip_is_an_error_not_a_blank_gap(self):
        with pytest.raises(ValueError):
            await PreviewTransport().write_raster_strip(b"\x1d\x76\x30\x00\x30\x00\x05\x00")

    @pytest.mark.asyncio
    async def test_there_is_no_link_to_query(self):
        t = PreviewTransport()
        assert t.has_notify is False
        assert await t.read_notify(10) == b""
        assert await t.scan() == []
        t.clear_notify_buffer()
        with pytest.raises(RuntimeError, match="GATT"):
            await t.read_gatt("2a19")

    @pytest.mark.asyncio
    async def test_status_queries_degrade_gracefully(self):
        printer, _ = _facade()
        info = await printer.query_full_info(timeout=0.01)
        assert info["escpos_status"] == {}
        assert info["ble_battery"] == {}

    @pytest.mark.asyncio
    async def test_png_output(self, tmp_path):
        printer, preview = _facade()
        await printer.print_image(_noise(384, 10))
        assert preview.png_bytes().startswith(PNG_SIGNATURE)
        out = tmp_path / "p.png"
        preview.save(out)
        with Image.open(out) as saved:
            assert saved.size == (384, 10)

    @pytest.mark.asyncio
    async def test_summary_mentions_what_cannot_be_rendered(self):
        printer, preview = _facade()
        await printer.print_image(_noise(384, 48))
        quiet = preview.summary()
        assert "384x48 px" in quiet and "2 raster strip(s)" in quiet and "native" not in quiet
        await printer.print_text("x")
        assert "1 native ESC/POS command(s) cannot be rendered" in preview.summary()

    def test_facade_reports_the_preview_as_connected(self):
        printer, preview = _facade()
        assert printer.is_connected_ble
        assert printer._ble is preview

    @pytest.mark.asyncio
    async def test_facade_disconnect_closes_the_preview(self):
        printer, preview = _facade()
        await printer.disconnect()
        assert not preview.is_connected
