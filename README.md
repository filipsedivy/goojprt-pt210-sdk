<div align="center">

# Unofficial GOOJPRT PT-210 SDK

*A Python driver for the 58 mm thermal printer that the vendor forgot to document.*

> Not affiliated with, endorsed by, or supported by GOOJPRT.
> Reverse-engineered from packet captures, sweat, and a little bit of thermal paper.

[![Powered by GitHub Copilot](https://img.shields.io/badge/Powered%20by-GitHub%20Copilot-24292e?logo=githubcopilot&logoColor=white)](https://github.com/features/copilot)
[![AIDD](https://img.shields.io/badge/Built%20with-AIDD-6f42c1)](https://en.wikipedia.org/wiki/Generative_artificial_intelligence)
[![PyPI](https://img.shields.io/pypi/v/goojprt-pt210-sdk)](https://pypi.org/project/goojprt-pt210-sdk/)
[![Docs](https://img.shields.io/badge/docs-readthedocs-blue)](https://goojprt-pt210-sdk.readthedocs.io)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)

</div>

> **AIDD — AI Driven Development**
> This project was written using AI-assisted development. The architecture, implementation, and documentation were produced through iterative collaboration with AI coding assistants (GitHub Copilot / Claude). Human judgment directed the design; AI did the heavy lifting.

---

## What is this?

The **GOOJPRT PT-210** is a compact 58 mm Bluetooth thermal printer sold under various white-label brands. GOOJPRT provides no official SDK, no protocol documentation, and no support for third-party integration. This library fills that gap.

It was created to enable reliable programmatic printing — text, barcodes, QR codes, bitmap images — from Python, without depending on proprietary Android apps or undocumented firmware quirks. The protocol was reverse-engineered from Bluetooth packet captures.

**Full documentation:** [goojprt-pt210-sdk.readthedocs.io](https://goojprt-pt210-sdk.readthedocs.io)

---

## Features

- **BLE (Bluetooth Low Energy)** — async, cross-platform (macOS, Windows, Linux)
- **SPP (classic RFCOMM)** — synchronous, Linux only
- **Text printing** — native ESC/POS code pages or bitmap rendering via Pillow (supports full Unicode and diacritics)
- **QR codes** — built-in ESC/POS QR generation
- **PDF417 barcodes** — pure-Python renderer, no native deps
- **Image printing** — any PIL image, with optional Floyd–Steinberg dithering
- **TOML templates** — declarative print layouts for receipts, labels, and tickets
- **Code-page probe** — built-in tool to test which firmware code pages actually work

---

## Installation

**From PyPI (stable):**

```bash
pip install goojprt-pt210-sdk
```

**With [uv](https://docs.astral.sh/uv/):**

```bash
uv add goojprt-pt210-sdk
```

**Latest from GitHub (development):**

```bash
pip install git+https://github.com/filipseedy/goojprt-pt210-sdk.git
```

**Editable install for local development:**

```bash
git clone https://github.com/filipseedy/goojprt-pt210-sdk.git
cd goojprt-pt210-sdk
pip install -e .
```

This installs the `goojprt` Python package and the `goojprt` CLI entry point.

**Requirements:** Python 3.14+, `bleak` (BLE), `Pillow` (image/bitmap rendering), `pdf417` (PDF417 barcodes).

---

## Quick start

```python
import asyncio
from goojprt import GoojPrtPT210

async def main() -> None:
    printer = GoojPrtPT210()
    await printer.connect_ble("XX:XX:XX:XX:XX:XX")
    await printer.initialize()
    await printer.print_text("Hello, world!")
    await printer.feed(3)
    await printer.disconnect()

asyncio.run(main())
```

### Print bitmap text (full Unicode / diacritics)

```python
await printer.print_text_image(
    "Příliš žluťoučký kůň\núpěl ďábelské ódy",
    font_size=28,
)
```

### Print a QR code

```python
await printer.print_qr("https://example.com", size=5)
```

### Print a PDF417 barcode

```python
await printer.print_pdf417("1234567890ABCDEF", columns=5, scale=2)
```

---

## CLI

```bash
# BLE demo print
goojprt XX:XX:XX:XX:XX:XX

# Bitmap text with antialiasing
goojprt XX:XX:XX:XX:XX:XX --print-image "Příliš žluťoučký kůň"

# PDF417 barcode
goojprt XX:XX:XX:XX:XX:XX --pdf417 "data"

# Print from a TOML template
goojprt XX:XX:XX:XX:XX:XX --template receipt.toml --var name=John

# Probe which code pages actually work on your unit
goojprt XX:XX:XX:XX:XX:XX --test
```

Run `goojprt --help` for all options.

---

## Two text paths

| Path | Method | Diacritics | Speed |
|------|--------|------------|-------|
| Native ESC/POS | `print_text` | Depends on firmware | Fast |
| Bitmap (Pillow) | `print_text_image` | Always correct | Slower |

If diacritics appear as garbage, switch to `print_text_image`. Use `--test` (or `probe_charsets()`) to test your specific unit.

---

## TOML templates

Define a print layout in a `.toml` file:

```toml
[[items]]
type = "text"
text = "Receipt — {{date}}"
bold = true
align = "center"

[[items]]
type = "qr"
data = "https://example.com/{{order_id}}"

[[items]]
type = "feed"
lines = 4
```

Variables like `{{date}}`, `{{time}}`, `{{expiry_7d}}` are built-in. Pass custom variables with `--var KEY=VALUE`.

---

## Documentation

Full API reference, architecture notes, and examples are at:

**[goojprt-pt210-sdk.readthedocs.io](https://goojprt-pt210-sdk.readthedocs.io)**

---

## License

MIT. See `LICENSE` for details.
