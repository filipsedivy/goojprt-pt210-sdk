"""Single-row multi-column (grid / table) renderer."""

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.encoding import find_system_font


def render_grid(
    columns: list[dict],
    font_size: int = 22,
    font_path: str | None = None,
    padding: int = 6,
    supersample: int = 3,
    dither: bool = False,
    threshold: int = 128,
):
    """Render a single row of a multi-column table as a 1-bit image.

    Each column is rendered into its own sub-canvas; text that overflows
    the column width is cropped automatically. Column widths are relative
    — they do not need to sum to 100; they are re-normalised to match
    the print head width.

    Each entry in ``columns`` is a mapping with the following keys:

    * ``width`` (``int``) — relative column width (e.g. ``40``, ``30``,
      ``30``).
    * ``align`` (``str``) — ``"left"`` / ``"center"`` / ``"right"``
      (default ``"left"``).
    * ``text`` (``str``) — cell content.

    Example TOML snippet consumed by :mod:`goojprt.template`::

        [[items]]
        type = "grid"
        font_size = 22
        dither = false
        columns = [
          {width = 40, align = "left",  text = "1 Kč"},
          {width = 30, align = "right", text = "5 ks"},
          {width = 30, align = "right", text = "5 Kč"},
        ]

    :param columns: Column definitions (see above).
    :param font_size: Font size in points.
    :param font_path: Optional ``.ttf`` path; falls back to
        :func:`find_system_font`.
    :param padding: Inner cell padding in pixels (pre-supersample).
    :param supersample: Oversampling factor for antialiasing.
    :param dither: Use Floyd–Steinberg (``True``) or threshold (``False``)
        during 1-bit conversion.
    :param threshold: Threshold for the non-dithered path (0–255).
    :returns: PIL image in mode ``"1"``.
    """
    from PIL import Image as PILImage, ImageDraw, ImageFont

    ss = max(1, supersample)
    render_width = PAPER_WIDTH_PX * ss

    resolved_font = font_path or find_system_font()
    try:
        font = ImageFont.truetype(resolved_font, font_size * ss) if resolved_font \
            else ImageFont.load_default()
    except (OSError, IOError):
        font = ImageFont.load_default()

    pad = padding * ss

    # Determine the height of the tallest piece of text in the row.
    probe_draw = ImageDraw.Draw(PILImage.new("L", (1, 1)))
    max_text_h = font_size * ss  # fallback
    for col in columns:
        text = col.get("text", "")
        if text:
            bb = probe_draw.textbbox((0, 0), text, font=font)
            max_text_h = max(max_text_h, bb[3] - bb[1])

    render_height = int(max_text_h) + 2 * pad

    # Convert relative widths to pixel widths.
    total_w = sum(col.get("width", 1) for col in columns) or 1
    col_widths_px: list[int] = []
    used = 0
    for i, col in enumerate(columns):
        if i == len(columns) - 1:
            # Last column absorbs the rounding remainder.
            col_widths_px.append(render_width - used)
        else:
            w = int(render_width * col.get("width", 1) / total_w)
            col_widths_px.append(w)
            used += w

    # Compose the row out of individual sub-canvases.
    canvas = PILImage.new("L", (render_width, render_height), 255)

    x_offset = 0
    for col, col_w in zip(columns, col_widths_px):
        text  = col.get("text", "")
        align = col.get("align", "left")

        # Sub-canvas for this column — overflow is cropped when pasted.
        sub = PILImage.new("L", (col_w, render_height), 255)
        if text:
            sub_draw = ImageDraw.Draw(sub)
            bb = probe_draw.textbbox((0, 0), text, font=font)
            text_w = bb[2] - bb[0]
            text_h = bb[3] - bb[1]
            y = (render_height - text_h) // 2  # vertically centred

            if align == "right":
                x = col_w - text_w - pad
            elif align == "center":
                x = (col_w - text_w) // 2
            else:  # left
                x = pad

            sub_draw.text((x, y), text, font=font, fill=0)

        canvas.paste(sub, (x_offset, 0))
        x_offset += col_w

    # Downscale to the print head width.
    target_height = max(1, round(render_height / ss))
    img = canvas.resize(
        (PAPER_WIDTH_PX, target_height),
        resample=PILImage.Resampling.LANCZOS,
    )

    if dither:
        return img.convert("1")
    return img.point(lambda p: 0 if p < threshold else 255).convert("1")  # type: ignore[arg-type]
