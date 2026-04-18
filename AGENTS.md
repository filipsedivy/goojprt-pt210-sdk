# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Repository state: in-progress package refactor

The repo is mid-refactor from a flat layout into a proper `goojprt/` package. Both copies currently coexist:

- **Root-level modules** (`commands.py`, `constants.py`, `encoding.py`, `enums.py`, `raster.py`, `rendering.py`, `transport.py`) — **stale**. Older versions with Czech docstrings. Do not edit these; treat them as the pre-refactor snapshot.
- **`goojprt/` subpackage** (`commands.py`, `constants.py`, `encoding.py`, `enums.py`, `raster.py`, `rendering/`, `transport/`) — **authoritative**. Newer versions with English docstrings. The `rendering/` and `transport/` monoliths have been split into proper subpackages.
- **Root orchestrators** (`__init__.py`, `__main__.py`, `cli.py`, `printer.py`, `template.py`) — import from `goojprt.*`, but haven't been moved *into* `goojprt/` yet. `goojprt/__init__.py` does not exist, so `import goojprt` currently fails. Completing the refactor means moving these five files into `goojprt/` and deleting the stale root copies.

When asked to modify a module, edit the `goojprt/` copy. Before declaring a change done, consider whether the stale root copy should be removed rather than kept in sync.

## Runtime

- **Python 3.14** required (`.python-version`, `pyproject.toml`).
- **Dependencies are not declared** in `pyproject.toml` but the code uses `bleak` (BLE) and `Pillow` (rendering). Both are imported lazily inside the functions that need them so unrelated code paths still work without them.
- **No tests, no CI, no lint config** committed. A `.ruff_cache/` exists (ruff 0.15.4) so ruff is used ad-hoc.
- Intended CLI entry: `python -m goojprt <bluetooth-address> [flags]` (see `cli.py:build_parser` for flags, including `--print-image`, `--pdf417`, `--template`, `--test`, `--test-cp1250`). This won't run until the refactor above is finished.

## Architecture

### Two parallel transports, no common base

`goojprt/transport/` intentionally does *not* expose an abstract `Transport` class. BLE is async (`bleak`), SPP is sync (`socket`, Linux-only); a shared interface would be leaky. `GoojPrtPT210` (in `printer.py`) is a facade that holds `_ble: BleTransport | None` and `_spp: SppTransport | None`, lazily instantiated by `connect_ble()` / `connect_spp()`. Every high-level print method has a BLE variant (`print_text`) and an SPP variant (`print_text_spp`); both delegate to the same byte builders in `commands.py`, so the wire format is identical.

`BleTransport.write()` chunks at `CHUNK_SIZE = 182` bytes and sleeps `CHUNK_DELAY = 0.04` s between chunks because it uses `write-without-response` (no link-layer ACK). After a raster image, `write_image_data()` additionally sleeps `max(0.3, rows * 0.002)` s to let the paper motor catch up.

### Pure byte builders, stateful transports

`goojprt/commands.py` is side-effect-free: every function returns the ESC/POS byte sequence for one command (`init`, `align`, `bold`, `feed`, `charset`, `barcode_qr`, …) or a composite (`build_text_block`, `build_qr_block`). Transport modules are the only place I/O happens. This separation is why BLE and SPP can share wire format trivially.

### Two text paths: native vs bitmap

There are two ways to print text, and the choice matters for diacritics:

1. **Native ESC/POS** (`print_text` / `print_text_spp`): emits `ESC t n` charset + encoded bytes. Fast, but relies on the printer firmware actually shipping the requested code page. Cheap GoojPrt units often ship only a subset; `CodePage.WPC1250` / `PC852` may silently produce garbage even if accepted.
2. **Bitmap** (`print_text_image`): renders via Pillow at `supersample`× resolution, downsamples with LANCZOS, optionally Floyd–Steinberg dithers, then feeds through `raster.image_to_raster`. Always correct for any Unicode, but slower and larger over BLE.

When a user reports diacritic corruption, the usual answer is to switch from native to bitmap. `probe_charsets()` on `GoojPrtPT210` prints a side-by-side test page.

### Rendering → raster → wire

All renderers in `goojprt/rendering/` (text, grid, pdf417, ekg) are pure: they take parameters and return a 1-bit `PIL.Image.Image`. They never touch a transport. `raster.image_to_raster(img)` is the single bridge that converts a PIL image to the `GS v 0` raster payload, padding/cropping to `PAPER_WIDTH_PX = 384` (hardware print head: 48 mm at 203 DPI). `raster.pad_image_to_paper_width(img, align)` is used for narrower bitmaps (typically barcodes) that need paper-relative positioning.

Pillow is imported lazily inside each renderer so the non-rendering parts of the SDK (commands, transports) stay usable without Pillow installed.

### TOML templates

`template.py` implements a small templating layer for the CLI's `--template` flag: loads a `.toml` file with an `items = [...]` array, substitutes `{{variables}}` (built-ins in `build_vars()` cover dates/times/expiries/passwords; user vars via `--var KEY=VALUE`), dispatches each item by `type` (`text`, `text_image`, `pdf417`, `qr`, `line`, `feed`, `cut`, `grid`, `ekg`) to the matching `GoojPrtPT210` method. BLE only.

## Conventions

- **Language**: All docstrings, comments, variable names, function names, log/print messages, and any other text in the codebase must be written in English. Czech content in existing files (`printer.py`, `template.py`, `cli.py`, root-level stale modules) is legacy and should be migrated to English whenever those files are touched.
- **`_print_template` re-export**: `__init__.py` re-exports `print_template` as `_print_template` for backward compatibility with an external caller (`pokladna_wizard.py`). Keep this alias.