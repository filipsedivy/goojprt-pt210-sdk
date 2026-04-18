"""PIL-based rendering pipelines for the GoojPrt PT-210.

Every renderer in this package is pure: it takes text/data and a handful
of style parameters and returns a 1-bit :class:`PIL.Image.Image` ready to
be passed to :func:`goojprt.raster.image_to_raster`. No renderer touches
the transport layer.

Pillow is imported lazily inside the individual renderers so that the
rest of the SDK can be used on installations without Pillow.
"""

from goojprt.rendering.ekg import render_ekg
from goojprt.rendering.grid import render_grid
from goojprt.rendering.pdf417 import render_pdf417
from goojprt.rendering.text import render_text_image

__all__ = [
    "render_text_image",
    "render_grid",
    "render_pdf417",
    "render_ekg",
]
