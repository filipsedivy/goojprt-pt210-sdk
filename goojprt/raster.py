"""Bridge between :mod:`PIL.Image` objects and ESC/POS raster byte streams.

This module is pure (no I/O) and is responsible for turning a PIL image
into the byte payload of the ``GS v 0`` (raster bit image) command that
the PT-210 firmware uses to print bitmaps.

Pillow is imported lazily inside each function so that the rest of the
SDK (``commands``, ``transport``, …) can still be used on installations
where Pillow is not available.
"""

from goojprt.constants import PAPER_WIDTH_PX
from goojprt.enums import Align


def image_to_raster(image) -> bytes:
    """Convert a PIL image into the ``GS v 0`` raster payload.

    The image is first converted to 1-bit mode, then either cropped or
    padded with white to exactly :data:`~goojprt.constants.PAPER_WIDTH_PX`
    pixels wide. The output consists of the ``GS v 0`` header (normal
    mode; width and height encoded as little-endian 16-bit values),
    followed by the pixel data in row-major order with eight pixels per
    byte (MSB = leftmost pixel; ``1`` = black, ``0`` = white).

    :param image: PIL image in any mode. It will be converted to mode
        ``"1"`` internally.
    :returns: A full ESC/POS ``GS v 0`` command ready to send to the
        printer.
    """
    from PIL import Image as PILImage

    img = image.convert("1")

    # Crop or pad to the print head width.
    if img.width > PAPER_WIDTH_PX:
        img = img.crop((0, 0, PAPER_WIDTH_PX, img.height))
    elif img.width < PAPER_WIDTH_PX:
        canvas = PILImage.new("1", (PAPER_WIDTH_PX, img.height), 1)
        canvas.paste(img, (0, 0))
        img = canvas

    import numpy as np

    width_bytes = PAPER_WIDTH_PX // 8
    result = bytearray()

    # GS v 0 m xL xH yL yH   (m = 0 → normal, no scaling)
    result += bytes([
        0x1D, 0x76, 0x30, 0x00,
        width_bytes & 0xFF, (width_bytes >> 8) & 0xFF,
        img.height & 0xFF, (img.height >> 8) & 0xFF,
    ])

    # PIL mode "1": False/0 = black, True/1 = white.
    # ESC/POS: 1 bit = black, 0 bit = white, MSB = leftmost pixel.
    arr = np.asarray(img, dtype=np.uint8)
    bits = (arr == 0).astype(np.uint8)
    result += np.packbits(bits, axis=1).tobytes()

    return bytes(result)


def image_to_raster_strips(image, strip_height: int = 24) -> list[bytes]:
    """Split *image* into horizontal strips and return each as a ``GS v 0`` payload.

    Each strip is a self-contained raster command. Consecutive strips are
    seamless on paper because the printer's paper motor advances by exactly
    the number of rows declared in each ``GS v 0`` header.

    :param image: PIL image in any mode. Converted to ``"1"`` internally.
    :param strip_height: Number of rows per strip (default 24 → 1 152 bytes
        of pixel data per strip, safe for small printer buffers).
    :returns: List of ``GS v 0`` byte payloads, one per strip.
    """
    from PIL import Image as PILImage
    import numpy as np

    img = image.convert("1")

    if img.width > PAPER_WIDTH_PX:
        img = img.crop((0, 0, PAPER_WIDTH_PX, img.height))
    elif img.width < PAPER_WIDTH_PX:
        canvas = PILImage.new("1", (PAPER_WIDTH_PX, img.height), 1)
        canvas.paste(img, (0, 0))
        img = canvas

    width_bytes = PAPER_WIDTH_PX // 8
    total_rows = img.height
    strips = []

    for y in range(0, total_rows, strip_height):
        rows = min(strip_height, total_rows - y)
        band = img.crop((0, y, PAPER_WIDTH_PX, y + rows))

        payload = bytearray()
        payload += bytes([
            0x1D, 0x76, 0x30, 0x00,
            width_bytes & 0xFF, (width_bytes >> 8) & 0xFF,
            rows & 0xFF, (rows >> 8) & 0xFF,
        ])

        arr = np.asarray(band, dtype=np.uint8)
        bits = (arr == 0).astype(np.uint8)
        payload += np.packbits(bits, axis=1).tobytes()

        strips.append(bytes(payload))

    return strips


def pad_image_to_paper_width(image, align: Align):
    """Pad a narrower image to :data:`PAPER_WIDTH_PX` with white background.

    Images wider than or equal to the paper width are returned unchanged.
    Used for objects (typically barcodes such as PDF417) whose rendered
    width is smaller than the print head and need to be positioned on the
    paper without being stretched.

    :param image: PIL image in mode ``"1"``.
    :param align: Horizontal alignment inside the padded canvas.
    :returns: A PIL image with width equal to
        :data:`~goojprt.constants.PAPER_WIDTH_PX`.
    """
    from PIL import Image as PILImage

    if image.width >= PAPER_WIDTH_PX:
        return image

    canvas = PILImage.new("1", (PAPER_WIDTH_PX, image.height), 1)
    if align == Align.CENTER:
        offset = (PAPER_WIDTH_PX - image.width) // 2
    elif align == Align.RIGHT:
        offset = PAPER_WIDTH_PX - image.width
    else:  # LEFT
        offset = 0
    canvas.paste(image, (offset, 0))
    return canvas
