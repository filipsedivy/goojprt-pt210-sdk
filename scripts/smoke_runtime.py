"""Exercise every bitmap path with the runtime dependencies only.

The regular test run installs the dev dependency group as well, so a package
that the SDK imports but ``pyproject.toml`` does not declare would go
unnoticed there. Run this script in an environment that holds just what
``pip install goojprt-pt210-sdk`` would install::

    uv run --isolated --no-dev --frozen python scripts/smoke_runtime.py
"""

from goojprt import raster
from goojprt.rendering import render_ekg, render_grid, render_pdf417, render_text_image

RENDERERS = {
    "text": lambda: render_text_image("Příliš žluťoučký kůň"),
    "grid": lambda: render_grid([{"width": 1, "align": "left", "text": "A"},
                                 {"width": 1, "align": "right", "text": "B"}]),
    "pdf417": lambda: render_pdf417("GoojPrt-PT210"),
    "ekg": lambda: render_ekg(),
    "ekg-portrait": lambda: render_ekg(portrait=True, beats=2),
}

for name, render in RENDERERS.items():
    payload = raster.image_to_raster(render())
    assert payload[:4] == b"\x1d\x76\x30\x00", f"{name}: not a GS v 0 raster"
    print(f"ok  {name:<13} {len(payload):>6} bytes")
print("runtime dependencies are sufficient")
