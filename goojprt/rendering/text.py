"""Multi-line bitmap text rendering with antialiasing and optional sharpening."""

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.encoding import find_system_font
from goojprt.enums import Align


def render_text_image(
    text: str,
    font_size: int = 24,
    font_path: str | None = None,
    line_spacing: int = 6,
    padding: int = 8,
    align: "Align | None" = None,
    supersample: int = 3,
    dither: bool = True,
    threshold: int = 140,
    sharpen: bool = False,
    sharpen_radius: float = 1.5,
    sharpen_percent: int = 180,
    sharpen_threshold: int = 2,
):
    """Render a multi-line string as a 1-bit image ready for the print head.

    The pipeline has four stages:

    1. **Supersampled rendering.** The text is drawn into a grayscale
       canvas ``supersample`` times larger than the final output. PIL's
       builtin antialiasing produces fully smooth diagonals with no
       staircasing.
    2. **Downscale to paper width** using ``LANCZOS`` resampling. The
       grayscale transitions carry the antialiasing information into the
       target resolution.
    3. **Optional unsharp-mask sharpening.** Applied before 1-bit
       conversion to boost perceived sharpness on thermal paper.
    4. **1-bit conversion** suitable for the print head:

       * ``dither=True`` — Floyd–Steinberg error diffusion. Best choice
         for small / body text: the grayscale gradient is converted into
         a dot pattern that preserves the antialiased look.
       * ``dither=False`` — pure threshold. Perfectly crisp edges, ideal
         for large headlines and barcodes.

    :param text: Multi-line input text (``\\n`` splits lines).
    :param font_size: Font size in points (rendered at
        ``font_size × supersample``).
    :param font_path: Optional path to a ``.ttf`` / ``.ttc`` file. Falls
        back to :func:`find_system_font` when ``None``.
    :param line_spacing: Extra pixels between lines (pre-supersample).
    :param padding: Outer canvas padding in pixels (pre-supersample).
    :param align: Horizontal alignment (:class:`Align`), default
        ``Align.LEFT``.
    :param supersample: Oversampling factor 1–4 (default ``3``, a good
        quality/speed trade-off).
    :param dither: ``True`` for Floyd–Steinberg, ``False`` for threshold.
    :param threshold: Threshold 0–255 for the ``dither=False`` path
        (lower = darker).
    :param sharpen: Apply :class:`PIL.ImageFilter.UnsharpMask` before
        1-bit conversion.
    :param sharpen_radius: Blur radius of the unsharp mask.
    :param sharpen_percent: Unsharp-mask intensity in percent.
    :param sharpen_threshold: Minimum brightness delta that triggers
        sharpening.
    :returns: PIL image in mode ``"1"`` with width
        :data:`~goojprt.constants.PAPER_WIDTH_PX`.
    """
    from PIL import Image as PILImage, ImageDraw, ImageFont, ImageFilter

    ss = max(1, supersample)
    render_width = PAPER_WIDTH_PX * ss

    resolved_font = font_path or find_system_font()
    try:
        # Font is rendered at the super-sampled size.
        font = ImageFont.truetype(resolved_font, font_size * ss) if resolved_font \
            else ImageFont.load_default()
    except (OSError, IOError):
        font = ImageFont.load_default()

    lines = text.splitlines() or [""]
    probe_draw = ImageDraw.Draw(PILImage.new("L", (1, 1)))
    line_dims: list[tuple[int, int]] = []
    for line in lines:
        bb = probe_draw.textbbox((0, 0), line or " ", font=font)
        line_dims.append((bb[2] - bb[0], bb[3] - bb[1]))

    pad = padding * ss
    sp  = line_spacing * ss
    render_height = sum(h for _, h in line_dims) + sp * (len(lines) - 1) + 2 * pad

    # Draw on a large grayscale canvas so PIL performs full antialiasing.
    canvas = PILImage.new("L", (render_width, render_height), 255)
    draw = ImageDraw.Draw(canvas)

    y = pad
    for i, line in enumerate(lines):
        lw, lh = line_dims[i]
        align_val = int(align) if align is not None else 0
        if align_val == 0:    # LEFT
            x = pad
        elif align_val == 1:  # CENTER
            x = (render_width - lw) // 2
        else:                 # RIGHT
            x = render_width - lw - pad
        draw.text((int(x), int(y)), line, font=font, fill=0)
        y += lh + sp

    # Downsample to the print head width — LANCZOS is the best choice here.
    target_height = max(1, round(render_height / ss))
    img = canvas.resize(
        (PAPER_WIDTH_PX, target_height),
        resample=PILImage.Resampling.LANCZOS,
    )

    # Optional sharpening before 1-bit conversion.
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=sharpen_radius,
            percent=sharpen_percent,
            threshold=sharpen_threshold,
        ))

    # 1-bit conversion for the print head.
    if dither:
        # Floyd–Steinberg: per-pixel error is propagated to neighbours,
        # producing a dot pattern that preserves the antialiased look.
        return img.convert("1")
    # Pure threshold: razor-sharp edges with zero noise around the glyphs.
    return img.point(lambda p: 0 if p < threshold else 255).convert("1")  # type: ignore[arg-type]
