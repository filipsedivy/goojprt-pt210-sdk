# goojprt/rendering/image_print.py
"""Pure image preparation pipeline for thermal printing."""

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align


def prepare_image(
    img,
    *,
    rotate: int = 0,
    crop: tuple[float, float, float, float] | None = None,
    scale: float = 1.0,
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
    target_w = max(1, int(scale * w))
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
