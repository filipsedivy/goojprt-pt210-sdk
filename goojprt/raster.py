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


def _normalize_to_paper_width(img):
    """Crop or pad *img* (mode ``"1"``) to exactly ``PAPER_WIDTH_PX`` wide.

    :param img: PIL image already converted to mode ``"1"``.
    :returns: PIL image with ``width == PAPER_WIDTH_PX``.
    """
    from PIL import Image as PILImage

    if img.width > PAPER_WIDTH_PX:
        return img.crop((0, 0, PAPER_WIDTH_PX, img.height))
    if img.width < PAPER_WIDTH_PX:
        canvas = PILImage.new("1", (PAPER_WIDTH_PX, img.height), 1)
        canvas.paste(img, (0, 0))
        return canvas
    return img


#: Byte → bit-inverted byte lookup, used with :meth:`bytes.translate`.
_INVERT_BITS = bytes(range(255, -1, -1))


def _pack_bits(band) -> bytes:
    """Convert a 1-bit PIL image band to packed ESC/POS pixel bytes.

    PIL mode ``"1"``: ``False``/``0`` = black, ``True``/``1`` = white.
    ESC/POS: ``1`` bit = black, ``0`` bit = white, MSB = leftmost pixel.

    PIL already packs mode ``"1"`` rows MSB-first, so the only work left is
    inverting the polarity. Rows whose width is not a multiple of 8 are
    padded with white first so the padding bits never print.

    :param band: PIL image in mode ``"1"``.
    :returns: Packed bytes, one bit per pixel, MSB first.
    """
    if band.width % 8:
        from PIL import Image as PILImage

        padded = PILImage.new("1", (band.width + 8 - band.width % 8, band.height), 1)
        padded.paste(band, (0, 0))
        band = padded
    return band.tobytes().translate(_INVERT_BITS)


def raster_to_image(payload: bytes):
    """Decode a ``GS v 0`` payload back into a PIL image (the inverse of packing).

    Used by the preview transport; also handy in tests. Only normal-mode
    payloads as built by :func:`image_to_raster` and
    :func:`image_to_raster_strips` are understood. Bytes after the pixel
    data are ignored.

    :param payload: A ``GS v 0`` command including its 8-byte header.
    :returns: PIL image in mode ``"1"``, ``width_bytes * 8`` pixels wide.
    :raises ValueError: When the header is not ``GS v 0 0`` or the pixel
        data is shorter than the header announces.
    """
    from PIL import Image as PILImage

    if len(payload) < 8 or payload[:4] != b"\x1d\x76\x30\x00":
        raise ValueError("not a GS v 0 raster payload (normal mode)")
    width_bytes = payload[4] | (payload[5] << 8)
    rows = payload[6] | (payload[7] << 8)
    expected = width_bytes * rows
    pixels = payload[8:8 + expected]
    if len(pixels) != expected:
        raise ValueError(f"truncated raster: header announces {expected} bytes, got {len(pixels)}")
    return PILImage.frombytes("1", (width_bytes * 8, rows), pixels.translate(_INVERT_BITS))


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
    img = _normalize_to_paper_width(image.convert("1"))

    width_bytes = PAPER_WIDTH_PX // 8
    result = bytearray()

    # GS v 0 m xL xH yL yH   (m = 0 → normal, no scaling)
    result += bytes([
        0x1D, 0x76, 0x30, 0x00,
        width_bytes & 0xFF, (width_bytes >> 8) & 0xFF,
        img.height & 0xFF, (img.height >> 8) & 0xFF,
    ])
    result += _pack_bits(img)

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
    img = _normalize_to_paper_width(image.convert("1"))

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
        payload += _pack_bits(band)

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
