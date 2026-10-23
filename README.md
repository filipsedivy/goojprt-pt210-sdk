<div align="center">

# Unofficial GOOJPRT PT-210 SDK

*A Python driver for the 58 mm thermal printer that the vendor forgot to document.*

> Not affiliated with, endorsed by, or supported by GOOJPRT.
> Reverse-engineered from packet captures, sweat, and a little bit of thermal paper.

[![Powered by GitHub Copilot](https://img.shields.io/badge/Powered%20by-GitHub%20Copilot-24292e?logo=githubcopilot&logoColor=white)](https://github.com/features/copilot)
[![codecov](https://codecov.io/github/filipsedivy/goojprt-pt210-sdk/graph/badge.svg?token=27CNTLK29B)](https://codecov.io/github/filipsedivy/goojprt-pt210-sdk)
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

There are two variants of the package:

| Variant | What you get | Install extra |
|---------|-------------|---------------|
| **SDK only** (default) | `goojprt` Python package + `goojprt` CLI | *(none)* |
| **SDK + Server** | everything above + `goojprt-server` — a FastAPI HTTP print server with live dashboard and REST API | `[server]` |

### pip

```bash
# SDK only
pip install goojprt-pt210-sdk

# SDK + HTTP print server
pip install "goojprt-pt210-sdk[server]"
```

### uv

```bash
# SDK only
uv add goojprt-pt210-sdk

# SDK + HTTP print server
uv add "goojprt-pt210-sdk[server]"
```

### Latest from GitHub (development)

```bash
# SDK only
pip install git+https://github.com/filipseedy/goojprt-pt210-sdk.git

# SDK + HTTP print server
pip install "git+https://github.com/filipseedy/goojprt-pt210-sdk.git#egg=goojprt-pt210-sdk[server]"
```

### Editable install for local development

```bash
git clone https://github.com/filipseedy/goojprt-pt210-sdk.git
cd goojprt-pt210-sdk

# SDK only
pip install -e .

# SDK + HTTP print server
pip install -e ".[server]"
```

**Requirements:** Python 3.14+. Core dependencies (`bleak`, `Pillow`, `pdf417`) are installed automatically. The `[server]` extra adds FastAPI, Uvicorn, Jinja2, Rich, and Pydantic.

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

The session helper connects, initialises and always disconnects, also when printing fails:

```python
async with GoojPrtPT210.ble("XX:XX:XX:XX:XX:XX") as printer:
    await printer.print_text("Hello, world!")
    await printer.feed(3)
```

(`GoojPrtPT210.spp(...)` does the same for classic Bluetooth with a plain `with`.)

### Print bitmap text (full Unicode / diacritics)

```python
await printer.print_text_image(
    "Příliš žluťoučký kůň\núpěl ďábelské ódy",
    font_size=28,
)
```

Lines wider than the paper are word-wrapped (`wrap=False` to turn that off).

### Print an image

```python
from PIL import Image
from goojprt.rendering.image_print import prepare_image

await printer.print_image(prepare_image(Image.open("photo.jpg")))        # scaled down to the paper
await printer.print_image(prepare_image(Image.open("logo.png"), fit="width", dither=False))
```

`fit="shrink"` (the default) never makes the picture wider than the paper, `"width"` fills the paper, `"none"` keeps the source size and cuts off whatever is wider.

### Print darker or lighter

```python
await printer.initialize()
await printer.set_density("dark")        # or "light", "normal", or a heating time 0-255
```

The presets are uncalibrated starting points, and whether a given unit honours `ESC 7` has not been verified.

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
# Find the printer (on macOS the "address" is a UUID), then keep it in the environment
goojprt --scan
export GOOJPRT_ADDRESS=XX:XX:XX:XX:XX:XX      # optional: the address argument can then be left out

# BLE demo print
goojprt XX:XX:XX:XX:XX:XX

# Native text with Czech diacritics: calibrate once, then print (see "Native Czech" below)
goojprt XX:XX:XX:XX:XX:XX --calibrate
goojprt XX:XX:XX:XX:XX:XX --print-text "Příliš žluťoučký kůň"

# Bitmap text with antialiasing
goojprt XX:XX:XX:XX:XX:XX --print-image "Příliš žluťoučký kůň"

# An image file, scaled down to the paper, printed darker
goojprt XX:XX:XX:XX:XX:XX --print-file photo.jpg --density dark

# PDF417 barcode
goojprt XX:XX:XX:XX:XX:XX --pdf417 "data"

# Print from a TOML template
goojprt XX:XX:XX:XX:XX:XX --template receipt.toml --var name=John

# Probe which code pages actually work on your unit
goojprt XX:XX:XX:XX:XX:XX --test
```

Run `goojprt --help` for all options.

### Preview without a printer

`--preview OUT.png` renders `--template`, `--print-image`, `--print-file` and `--pdf417` into a PNG instead of printing, so layouts can be built without wasting paper (and without an address):

```bash
goojprt --template examples/receipt.toml --var shop="Corner Shop" --var total=12.50 --preview receipt.png
```

Everything drawn as a bitmap appears exactly as it would print — the preview is checked pixel for pixel against the real raster stream. Native ESC/POS text (`text` items, `print_text`), separator lines and QR codes are produced by the printer firmware and cannot be rendered; they show up as dashed notes with their content, and the command reports how many there were.

In Python, `printer.connect_preview()` attaches the same recorder to any facade, and the server offers `POST /api/preview/{text,pdf417,ekg,grid,image}` which return the PNG (header `X-Preview-Native-Commands` counts the unrenderable parts). Previews never touch the print queue or the printer.

```python
printer = GoojPrtPT210()
preview = printer.connect_preview()
await printer.print_text_image("Příliš žluťoučký kůň")
preview.save("preview.png")
```

---

## Two text paths

| Path | Method | Diacritics | Speed |
|------|--------|------------|-------|
| Native ESC/POS | `print_text` | Depends on firmware | Fast |
| Bitmap (Pillow) | `print_text_image` | Always correct | Slower |

If diacritics appear as garbage, switch to `print_text_image`. Use `--test` (or `probe_charsets()`) to test your specific unit.

Characters that the chosen `encoding` cannot represent are printed as `?` (and a warning is logged) rather than being sent as UTF-8, which the printer would render as garbage.

### Native Czech (or any language) without bitmaps

Bitmap text always works, but native text is faster and much smaller on the wire. Which `ESC t` table prints your language correctly differs from unit to unit, and many cheap printers boot in a double-byte (Chinese) mode in which bytes ≥ 0x80 are half of a character, so a table can look wrong even after `ESC t`. Find the right combination once:

```bash
goojprt XX:XX:XX:XX:XX:XX --calibrate
```

It prints the Czech test sentence once per candidate — tables 18 (cp852), 45 (cp1250), 39 (iso8859-2) and 16, each with and without `FS .` (cancel Chinese mode) — labelled A–H, asks which line shows the sentence exactly and saves the answer (`--calibrate-pick LETTER` saves without printing, `--calibrate-text` uses your own sentence). After that:

```bash
goojprt XX:XX:XX:XX:XX:XX --print-text "Příliš žluťoučký kůň úpěl ďábelské ódy"
goojprt XX:XX:XX:XX:XX:XX --template examples/native-text-czech.toml
```

Both use the saved profile on their own (`--profile FILE` / `--no-profile` override it; the file lives in `$GOOJPRT_PROFILE` or `~/.config/goojprt/profile.toml`). Each line is printed natively when the table can show it and rendered as a bitmap only when it cannot (a euro sign in cp852), so nothing ever comes out as garbage.

In Python the same is three lines, and `print_text` then needs no `encoding=`:

```python
await printer.use_codepage(CodePage.PC852)              # FS . + ESC t 18, remembers the codec
await printer.print_text("Příliš žluťoučký kůň")        # native, cp852
await printer.print_text_auto("Cena 5 € za kus")        # native where possible, bitmap for the euro line
```

The profile is sent again with every `initialize()` and after reconnects. Templates have a `codepage` item for the same thing, text items take `auto = true`, the server's text jobs take `"auto": true` and use a profile given with `--profile` / `GOOJPRT_PROFILE`. If nothing looks right, `print_text_image` always works.

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

Variables like `{{date}}`, `{{time}}`, `{{expire_24h}}`, `{{password_12}}` are built-in. Pass custom variables with `--var KEY=VALUE`.

Item types: `text`, `text_image`, `image`, `qr`, `pdf417`, `grid`, `ekg`, `line`, `feed`, `cut`, `charset`, `chinese_mode`, `codepage`, `density`. A `codepage` item (`code_page = "PC852"`) switches to a native code page and makes `text` items encode for it. An `image` item (`path` is relative to the template file, plus `fit`, `scale`, `align`, `dither`, …) prints a logo; it is opened before the printer is touched, so a missing file fails before any paper is used. Ready-to-run samples are in [`examples/`](examples/): a receipt with a logo, a guest Wi-Fi voucher with a QR code, and a native-text experiment.

---

## How the printer talks

- **BLE:** the primary UUIDs (`49535343-…`) are Microchip's *Transparent UART* service (BM70/RN4870 modules): GATT writes go to the module, which forwards them over a UART to the printer MCU. There is no flow control, so the SDK writes in small chunks with a pause in between and waits after every raster strip. Some firmware uses the `0000ff00` service family instead; both are tried.
- **Protocol:** plain ESC/POS — `ESC @`, `GS ! n`, `GS ( k` (QR), `GS v 0` (raster, sent in 24-row strips), `DLE EOT n` / `GS I n` for status and identification (answers arrive on the notify characteristic, if the unit has one). See `goojprt.status` for decoding the status bytes.
- **Concurrency:** writes are serialised, so a status query from another task can never land in the middle of a print job.

Observed on one unit (`PT-210_DF5B`: manufacturer GEZHI, model PT2D-V1.0, firmware PT-210-8008) — other units or firmware may differ:

- It lists five services, among them both UUID families (`49535343-fe7d-…` and `0000ff00-…`). Write to `49535343-8841-…`; the answers to status and identification queries come back on `49535343-1e4d-…`, the notify characteristic *of the same service*, within 25–45 ms. The `0000ff01` notify characteristic of the other family stays silent, which is why the SDK pairs the notify characteristic with the write characteristic's service.
- `DLE EOT 1–4` answer one byte each (`0x16` online, `0x12` for "no cover / paper / error"); `GS r 1` and `ESC v` answer too. `GS I 1–3` return single ID bytes (`0x60`, `0x03`, `0x08`), `GS I 65–68` return text (firmware version, manufacturer, model, serial number), `GS I 97` returns `14 00 00 0f`. Nothing else in `GS I 0–127` answers.
- The negotiated write-without-response payload is 237 bytes, so the 182/192-byte chunks fit. On subscribing, `0000ff03` announces `01 04` and `02 b6 00` (0xB6 = 182) and is silent while printing, so it is not a flow-control channel; pacing stays open-loop. There is no Battery service.

The pacing is conservative. If your unit keeps up, print faster by lowering the pause (and raise it again if you see missing lines):

```python
await printer.connect_ble("XX:XX:XX:XX:XX:XX", chunk_delay=0.02)
```

---

## Upgrading

- `TextSize.DOUBLE_HEIGHT`, `DOUBLE_WIDTH` and `DOUBLE_BOTH` now produce 1×2, 2×1 and 2×2 characters as their names say. They used to send `0x11`, `0x20` and `0x31` (2×2, 3×1, 4×2), so existing output with `size=` will look different.
- `print_text` / `text_to_bytes` replace unencodable characters with `?` instead of switching the whole string to UTF-8.
- Images wider than the paper are now scaled down (`fit="shrink"`) instead of having their right part cut off when printed. Anything that already fitted — including callers that compensate with `scale` ≈ 384 / width — prints exactly as before; `fit="none"` restores the old behaviour for wide images.
- Bitmap text (`print_text_image`, `text_image` items, `render_text_image`) word-wraps lines wider than the paper instead of running them off the edge. Lines that fit are unchanged; pass `wrap=False` for the old behaviour.
- `print_text()` encodes with the codec of the active code page (after `set_charset`, `apply_profile` or `use_codepage`) when no `encoding=` is given; without one it is GB2312 as before. `text` template items and the server's text jobs follow the same rule, and `initialize()` re-sends an applied profile.
- The BLE transport subscribes to the notify characteristic of the *write characteristic's service*. Units that expose both UUID families used to be subscribed to a characteristic that never answers, so status, battery and identification queries returned nothing.
- `commands.energy()` raises `ValueError` outside 0–255 instead of wrapping the value around.
- `numpy` is no longer needed: bitmap printing used to fail with `ModuleNotFoundError` on a plain `pip install`.

---

## Documentation

Full API reference, architecture notes, and examples are at:

**[goojprt-pt210-sdk.readthedocs.io](https://goojprt-pt210-sdk.readthedocs.io)**

---

## License

MIT. See `LICENSE` for details.
