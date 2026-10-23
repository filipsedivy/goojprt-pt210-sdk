"""Tests for ``prepare_image(fit=...)`` and word wrapping in ``render_text_image``."""
import random

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.rendering.image_print import FIT_MODES, prepare_image
from goojprt.rendering.text import _wrap_line, render_text_image


def _photo(width: int, height: int, seed: int = 1) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (width, height))
    img.putdata([(rnd.randrange(256),) * 3 for _ in range(width * height)])
    return img


def _black_box(img: Image.Image):
    """Bounding box of the black pixels of a mode-1 image."""
    return ImageChops.invert(img.convert("L")).getbbox()


# ── fit ───────────────────────────────────────────────────────────────────────

class TestFit:
    def test_wide_source_is_scaled_down_not_cropped_by_default(self):
        result = prepare_image(Image.new("RGB", (1000, 500), (0, 0, 0)))
        assert result.width == PAPER_WIDTH_PX
        assert result.height == 192                    # 500 * 384 / 1000, aspect kept
        assert _black_box(result) == (0, 0, PAPER_WIDTH_PX, 192)   # the whole picture is there

    @pytest.mark.parametrize("width", [50, 200, 384])
    def test_sources_that_already_fit_are_untouched(self, width):
        img = _photo(width, width // 2)
        assert prepare_image(img).tobytes() == prepare_image(img, fit="none").tobytes()

    def test_scale_that_already_makes_it_fit_is_untouched(self):
        # Callers used to compensate with scale ~ 384 / width.
        img = _photo(1000, 500)
        assert (prepare_image(img, scale=0.384).tobytes()
                == prepare_image(img, scale=0.384, fit="none").tobytes())

    def test_shrink_only_clamps_the_final_width(self):
        assert prepare_image(Image.new("RGB", (1000, 100), 0), scale=0.2).width == PAPER_WIDTH_PX
        box = _black_box(prepare_image(Image.new("RGB", (1000, 100), 0), scale=0.2))
        assert box[2] - box[0] == 200                  # 0.2 * 1000, not enlarged to the paper

    def test_none_keeps_the_old_behaviour_of_not_limiting_the_width(self):
        assert prepare_image(Image.new("RGB", (1000, 500), 0), fit="none").width == 1000

    def test_width_enlarges_small_sources_to_the_paper(self):
        result = prepare_image(Image.new("RGB", (100, 50), 0), fit="width")
        assert _black_box(result) == (0, 0, PAPER_WIDTH_PX, 192)

    def test_width_scale_is_a_fraction_of_the_paper(self):
        result = prepare_image(Image.new("RGB", (100, 50), 0), fit="width", scale=0.5)
        left, _, right, _ = _black_box(result)
        assert right - left == PAPER_WIDTH_PX // 2
        assert left == (PAPER_WIDTH_PX - PAPER_WIDTH_PX // 2) // 2     # centred

    def test_width_never_exceeds_the_paper(self):
        assert prepare_image(Image.new("RGB", (100, 50), 0), fit="width", scale=3).width == PAPER_WIDTH_PX

    def test_alignment_still_applies(self):
        result = prepare_image(Image.new("RGB", (100, 50), 0), scale=1.0, align="right")
        assert _black_box(result)[2] == PAPER_WIDTH_PX

    def test_unknown_fit_is_rejected(self):
        with pytest.raises(ValueError, match="fit"):
            prepare_image(_photo(10, 10), fit="stretch")

    def test_documented_modes(self):
        assert set(FIT_MODES) == {"none", "shrink", "width"}


# ── wrap ──────────────────────────────────────────────────────────────────────

LONG = "Tohle je velmi dlouhý řádek textu, který se na papír o šířce 384 bodů nevejde"


def _dark_in_right_margin(img: Image.Image, columns: int) -> int:
    return sum(1 for y in range(img.height) for x in range(img.width - columns, img.width)
               if img.getpixel((x, y)) == 0)


class TestWrap:
    @pytest.mark.parametrize("text", [
        "Hello World\nDruhý řádek, krátký",
        "A\n\nB",
        "",
        "Střed",
    ])
    def test_text_that_fits_is_identical_with_and_without_wrap(self, text):
        assert (render_text_image(text, font_size=24).tobytes()
                == render_text_image(text, font_size=24, wrap=False).tobytes())

    def test_overflowing_line_runs_off_the_paper_without_wrap(self):
        # Guards the sensitivity of the next test.
        img = render_text_image(LONG, font_size=24, wrap=False)
        assert _dark_in_right_margin(img, 6) > 0

    def test_overflowing_line_wraps_inside_the_margins(self):
        single = render_text_image("Tohle", font_size=24, wrap=False)
        img = render_text_image(LONG, font_size=24)
        assert img.height > single.height * 1.8        # several lines now
        assert img.width == PAPER_WIDTH_PX
        assert _dark_in_right_margin(img, 6) == 0      # nothing in the right padding

    def test_explicit_newlines_are_kept_and_each_line_wraps_on_its_own(self):
        one = render_text_image(LONG, font_size=24)
        two = render_text_image(LONG + "\n" + LONG, font_size=24)
        assert two.height > one.height * 1.8

    def test_word_longer_than_a_line_is_broken_between_characters(self):
        img = render_text_image("X" * 200, font_size=24)
        assert img.height > 100
        assert _dark_in_right_margin(img, 6) == 0

    def test_a_glyph_wider_than_the_paper_terminates(self):
        # Every piece must contain at least one character, or this would hang.
        img = render_text_image("AB", font_size=300, supersample=1)
        assert img.height > 0

    @pytest.mark.parametrize("align", [0, 1, 2])
    def test_all_alignments_keep_wrapped_lines_inside(self, align):
        img = render_text_image(LONG, font_size=24, align=align)
        assert _dark_in_right_margin(img, 6) == 0


class TestWrapLine:
    @staticmethod
    def _measure():
        draw = ImageDraw.Draw(Image.new("L", (1, 1)))
        font = ImageFont.load_default(size=20)
        return draw, font

    def test_pieces_cover_all_words_in_order(self):
        draw, font = self._measure()
        text = "one two three four five six seven eight nine ten eleven twelve"
        pieces = _wrap_line(draw, text, font, max_width=120)
        assert len(pieces) > 1
        assert " ".join(pieces).split() == text.split()
        assert all(draw.textbbox((0, 0), p, font=font)[2] <= 120 for p in pieces)

    def test_fitting_line_is_returned_as_is(self):
        draw, font = self._measure()
        assert _wrap_line(draw, "  keeps   spaces ", font, max_width=10_000) == ["  keeps   spaces "]

    def test_empty_line(self):
        draw, font = self._measure()
        assert _wrap_line(draw, "", font, max_width=50) == [""]

    def test_long_word_is_split_into_fitting_chunks(self):
        draw, font = self._measure()
        pieces = _wrap_line(draw, "W" * 40, font, max_width=100)
        assert "".join(pieces) == "W" * 40
        assert len(pieces) > 1
        assert all(draw.textbbox((0, 0), p, font=font)[2] <= 100 for p in pieces)
