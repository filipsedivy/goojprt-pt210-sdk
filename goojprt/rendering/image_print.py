# goojprt/rendering/image_print.py
"""Pure image preparation pipeline for thermal printing."""

from typing import Literal

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align

#: How :func:`prepare_image` relates the output width to the paper width.
FitMode = Literal["none", "shrink", "width"]

FIT_MODES: tuple[str, ...] = ("none", "shrink", "width")


def _target_width(source_width: int, scale: float, fit: str) -> int:
    """Width in pixels the prepared image should have (before padding)."""
    if fit == "none":
        width = int(scale * source_width)
    elif fit == "shrink":
        width = min(int(scale * source_width), PAPER_WIDTH_PX)
    elif fit == "width":
        width = min(int(scale * PAPER_WIDTH_PX), PAPER_WIDTH_PX)
    else:
        raise ValueError(f"unknown fit mode {fit!r}; expected one of {', '.join(FIT_MODES)}")
    return max(1, width)


def prepare_image(
    img,
    *,
    rotate: int = 0,
    crop: tuple[float, float, float, float] | None = None,
    scale: float = 1.0,
    fit: FitMode = "shrink",
    brightness: float = 1.0,
    contrast: float = 1.0,
    threshold: int = 128,
    dither: bool = True,
    align: str = "center",
):
    """Prepare a PIL image for thermal printing.

    Returns a mode-``"1"`` image padded to PAPER_WIDTH_PX.

    Pipeline: rotate → crop → resize → brightness → contrast →
    grayscale → threshold/dither → pad to paper width.

    ``fit`` and ``scale`` decide the width of the resized image:

    * ``"shrink"`` (default) — ``scale`` multiplies the source width, but the
      result is never wider than the paper, so a large photo is scaled down
      instead of having its right part cut off. Anything that already fits
      comes out exactly as with ``"none"``.
    * ``"width"`` — ``scale`` is a fraction of the paper width: ``1.0`` fills
      the paper whatever the source size (small sources are enlarged).
    * ``"none"`` — ``scale`` multiplies the source width and nothing else;
      anything wider than the paper is cropped when printed.

    :raises ValueError: For an unknown ``fit`` mode.
    """
    from PIL import Image, ImageEnhance

    from goojprt.raster import pad_image_to_paper_width

    img = img.convert("RGB")

    if rotate:
        img = img.rotate(rotate, expand=True)

    if crop is not None:
        cx, cy, cw, ch = crop
        w, h = img.size
        left   = int(cx * w)
        upper  = int(cy * h)
        right  = int((cx + cw) * w)
        lower  = int((cy + ch) * h)
        right  = max(right, left + 1)
        lower  = max(lower, upper + 1)
        img = img.crop((left, upper, right, lower))

    w, h = img.size
    target_w = _target_width(w, scale, fit)
    target_h = max(1, int(h * target_w / w))
    img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    gray = img.convert("L")

    if dither:
        bw = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        bw = gray.point(lambda p: 255 if p > threshold else 0).convert("1", dither=Image.Dither.NONE)

    _align_map = {"left": Align.LEFT, "center": Align.CENTER, "right": Align.RIGHT}
    return pad_image_to_paper_width(bw, _align_map.get(align, Align.CENTER))
