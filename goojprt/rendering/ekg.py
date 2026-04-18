"""Synthetic ECG waveform generator rendered as a 1-bit bitmap.

The curve is built by summing a handful of Gaussians modelling the
classic PQRST waves:

    * **P** — atrial depolarisation (small positive bump).
    * **Q** — start of ventricular depolarisation (small negative dip).
    * **R** — ventricular depolarisation (dominant spike).
    * **S** — late ventricular depolarisation (small negative dip).
    * **T** — ventricular repolarisation (medium positive bump).

Two orientations are available:

* **Landscape** (``portrait=False``) — time runs across the paper width.
* **Portrait** (``portrait=True``) — time runs down the paper, amplitude
  runs across the width, giving an unlimited-length recording.
"""

from goojprt.constants import PAPER_WIDTH_PX


def render_ekg(
    beats: int = 4,
    height_px: int = 160,
    line_width: int = 2,
    grid: bool = True,
    grid_step_px: int = 32,
    amplitude: float = 0.82,
    portrait: bool = False,
    px_per_beat: int = 240,
):
    """Render a synthetic ECG strip.

    :param beats: Number of consecutive heartbeats on the strip.
    :param height_px: Landscape only — strip height in pixels. Ignored
        in portrait mode (height becomes ``beats × px_per_beat``).
    :param line_width: Curve thickness, 1–3 pixels.
    :param grid: Draw the standard dashed ECG grid.
    :param grid_step_px: Grid spacing in pixels (``32`` ≈ 4.7 mm at
        203 DPI).
    :param amplitude: Relative height of the R-wave, 0.0–1.0.
    :param portrait: Orientation selector (see module docstring).
    :param px_per_beat: Portrait only — pixels per heartbeat along the
        paper. More pixels means a more detailed curve.
    :returns: PIL image in mode ``"1"``.
    """
    import numpy as np

    WAVES = np.array([
        ( 0.14,  0.15,  0.018),   # P
        (-0.06,  0.245, 0.007),   # Q
        ( 1.00,  0.270, 0.009),   # R
        (-0.18,  0.300, 0.007),   # S
        ( 0.30,  0.440, 0.045),   # T
    ])  # shape (5, 3): columns are amplitude, mu, sigma

    def signal_array(t: np.ndarray) -> np.ndarray:
        """Evaluate ECG signal for an array of beat-local times ``t`` ∈ [0, 1]."""
        a, mu, sig = WAVES[:, 0], WAVES[:, 1], WAVES[:, 2]
        return np.sum(a * np.exp(-((t[:, None] - mu) ** 2) / (2 * sig ** 2)), axis=1)

    if portrait:
        return _render_ekg_portrait(
            beats, px_per_beat, line_width, grid, grid_step_px,
            amplitude, signal_array,
        )
    return _render_ekg_landscape(
        beats, height_px, line_width, grid, grid_step_px,
        amplitude, signal_array,
    )


def _render_ekg_landscape(beats, height_px, line_width, grid, grid_step_px,
                          amplitude, signal_array):
    """Render a landscape (time → horizontal) ECG strip."""
    import numpy as np
    from PIL import Image as PILImage, ImageDraw

    width = PAPER_WIDTH_PX
    i = np.arange(width)
    t = (i % (width / beats)) / (width / beats)
    raw = signal_array(t).tolist()

    sig_min, sig_max = min(raw), max(raw)
    sig_range = sig_max - sig_min or 1.0
    pad = int(height_px * 0.08)
    draw_h = height_px - 2 * pad

    def to_y(v):
        """Map an amplitude sample to its y coordinate."""
        norm = (v - sig_min) / sig_range
        norm = (norm - 0.5) * amplitude + 0.5
        return int(pad + (1.0 - norm) * draw_h)

    signal_y = [to_y(v) for v in raw]

    img = PILImage.new("L", (width, height_px), 255)
    draw = ImageDraw.Draw(img)

    if grid:
        dash_on, dash_off = 3, 4
        for gx in range(0, width, grid_step_px):
            y = 0
            while y < height_px:
                draw.line([(gx, y), (gx, min(y + dash_on, height_px))], fill=180, width=1)
                y += dash_on + dash_off
        for gy in range(0, height_px, grid_step_px):
            x = 0
            while x < width:
                draw.line([(x, gy), (min(x + dash_on, width), gy)], fill=180, width=1)
                x += dash_on + dash_off

    # Isoelectric baseline (dashed).
    baseline_y = to_y(0.0)
    x = 0
    while x < width:
        draw.line([(x, baseline_y), (min(x + 6, width), baseline_y)], fill=210, width=1)
        x += 10

    for x in range(width - 1):
        draw.line([(x, signal_y[x]), (x + 1, signal_y[x + 1])], fill=0, width=line_width)

    return img.convert("1")


def _render_ekg_portrait(beats, px_per_beat, line_width, grid, grid_step_px,
                         amplitude, signal_array):
    """Render a portrait (time → vertical) ECG strip.

    Produces an image of width :data:`PAPER_WIDTH_PX` and height
    ``beats × px_per_beat``, suitable for long scrolling recordings.
    """
    import numpy as np
    from PIL import Image as PILImage, ImageDraw

    width = PAPER_WIDTH_PX
    total_rows = beats * px_per_beat

    rows = np.arange(total_rows)
    t = (rows % px_per_beat) / px_per_beat
    raw = signal_array(t).tolist()

    sig_min, sig_max = min(raw), max(raw)
    sig_range = sig_max - sig_min or 1.0
    pad = int(width * 0.05)   # 5% margin on each side
    draw_w = width - 2 * pad

    def to_x(v: float) -> int:
        """Map an amplitude sample to its x coordinate (centre = zero line)."""
        norm = (v - sig_min) / sig_range
        norm = (norm - 0.5) * amplitude + 0.5
        return int(pad + norm * draw_w)

    signal_x = [to_x(v) for v in raw]

    img = PILImage.new("L", (width, total_rows), 255)
    draw = ImageDraw.Draw(img)

    # Grid — horizontal lines every grid_step_px rows (time ticks),
    # vertical lines every grid_step_px columns (amplitude ticks).
    if grid:
        dash_on, dash_off = 3, 4
        for gy in range(0, total_rows, grid_step_px):
            x = 0
            while x < width:
                draw.line([(x, gy), (min(x + dash_on, width), gy)], fill=180, width=1)
                x += dash_on + dash_off
        for gx in range(0, width, grid_step_px):
            y = 0
            while y < total_rows:
                draw.line([(gx, y), (gx, min(y + dash_on, total_rows))], fill=180, width=1)
                y += dash_on + dash_off

    # Isoelectric baseline — vertical dashed line in the centre.
    baseline_x = to_x(0.0)
    y = 0
    while y < total_rows:
        draw.line([(baseline_x, y), (baseline_x, min(y + 6, total_rows))], fill=210, width=1)
        y += 10

    # Dotted separator at each beat boundary.
    for beat_idx in range(1, beats):
        sep_y = beat_idx * px_per_beat
        x = 0
        while x < width:
            draw.point((x, sep_y), fill=150)
            x += 6

    # ECG curve — horizontal = amplitude, vertical = time.
    for row in range(total_rows - 1):
        draw.line(
            [(signal_x[row], row), (signal_x[row + 1], row + 1)],
            fill=0, width=line_width,
        )

    return img.convert("1")
