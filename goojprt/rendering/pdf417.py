"""PDF417 2D barcode rendering (requires the optional ``pdf417`` package)."""


def render_pdf417(
    data: str,
    scale: int = 2,
    row_height: int = 5,
    columns: int = 5,
    padding: int = 10,
    min_rows: int | None = None,
):
    """Render a PDF417 barcode as a monochrome PIL image.

    :param data: The text to encode.
    :param scale: Width of a single module in pixels.
    :param row_height: Height of each row in modules (default ``5`` gives
        a reasonably legible barcode; values below ``3`` are usually too
        thin to scan).
    :param columns: Number of data columns, 1–30. Fewer columns produce
        more rows.
    :param padding: White quiet zone in pixels.
    :param min_rows: Minimum number of rows. When the produced barcode
        has fewer rows, the number of columns is decreased until the
        constraint is satisfied (or ``columns`` reaches 1).
    :returns: PIL image in mode ``"1"``.

    Requires :mod:`pdf417` and :mod:`PIL` (``pip install pdf417 pillow``).
    """
    from pdf417 import encode, render_image

    cols = max(1, min(columns, 30))

    codes = encode(data, columns=cols)

    # Shrink the column count until the row-count floor is met.
    if min_rows is not None:
        while len(codes) < min_rows and cols > 1:
            cols -= 1
            codes = encode(data, columns=cols)

    img = render_image(codes, scale=scale, ratio=row_height, padding=padding)
    return img.convert("1")
