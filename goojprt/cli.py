"""Command-line interface for the GoojPrt PT-210 SDK.

Entry point: ``python -m goojprt <address> [flags]``. Flags are kept
stable with the historic standalone ``goojprt.py`` script so existing
shell snippets keep working. ``goojprt --scan`` lists nearby devices, and
``GOOJPRT_ADDRESS`` can replace the address argument.
"""

import argparse
import asyncio
import contextlib
import os
import sys
from collections.abc import AsyncIterator

from goojprt.commands import resolve_density
from goojprt.enums import Align, CodePage, TextSize
from goojprt.printer import GoojPrtPT210, disconnect_quietly
from goojprt.rendering.image_print import FIT_MODES
from goojprt.template import TemplateError, print_template

#: Environment variable that supplies the printer address when none is given.
ADDRESS_ENV = "GOOJPRT_ADDRESS"


@contextlib.asynccontextmanager
async def _connected(
    address: str | None,
    *,
    preview: str | None = None,
    density: "str | int | None" = None,
) -> AsyncIterator[GoojPrtPT210]:
    """Connect, initialise and always disconnect, even when the work inside fails.

    With ``preview`` no printer is used: everything is rendered into that PNG
    file, which is written when the work inside finishes without an error.
    ``density`` is applied right after the initialisation.
    """
    printer = GoojPrtPT210()
    transport = None
    if preview is None:
        print(f"Connecting to {address} ...")
        await printer.connect_ble(address)
        print("Connected.")
    else:
        transport = printer.connect_preview()
        print(f"Rendering into {preview} (no printer is used) ...")
    try:
        await printer.initialize()
        if density is not None:
            await printer.set_density(density)
        yield printer
        if transport is not None and preview is not None:
            transport.save(preview)
            print(f"Preview saved to {preview}: {transport.summary()}")
    finally:
        await disconnect_quietly(printer)


async def _scan(timeout: float, show_all: bool) -> None:
    """List nearby BLE devices so the user can find the printer's address."""
    print(f"Scanning for {timeout:g} s ...")
    try:
        devices = await GoojPrtPT210().scan_ble(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — Bluetooth off, no permission, bleak missing, …
        sys.exit(f"goojprt: scan failed: {exc}")
    shown = [d for d in devices if show_all or d["name"] != "?"]
    shown.sort(key=lambda d: (d["name"].lower(), d["address"]))
    if not shown:
        hint = "" if show_all else " with a name (--scan-all includes unnamed ones)"
        print(f"No Bluetooth LE devices{hint} found. Is the printer switched on and nearby?")
        return
    width = max(len(d["address"]) for d in shown)
    for device in shown:
        print(f"{device['address']:<{width}}  {device['name']}")
    print(f"\nUse the address as `goojprt <address> ...` or set {ADDRESS_ENV}.")


async def _demo_ble(address: str) -> None:
    """Self-contained BLE demo: text, QR, PDF417, diacritics (bitmap)."""
    async with _connected(address) as printer:
        await printer.print_text("=== GoojPrt PT-210 ===", align=Align.CENTER, bold=True)
        await printer.print_line()
        await printer.print_text("Normal text")
        await printer.print_text("Bold text", bold=True)
        await printer.print_text("Large text", size=TextSize.DOUBLE_BOTH)
        await printer.print_line()
        await printer.print_text("QR code:", align=Align.CENTER)
        await printer.print_qr("https://goojprt.com", size=5)
        await printer.print_line()
        await printer.print_text("PDF417:", align=Align.CENTER)
        await printer.print_pdf417("GoojPrt-PT210-TEST-123")
        await printer.print_line()

        await printer.set_charset(CodePage.PC852)
        await printer.print_text("CP852: Příliš žluťoučký kůň", encoding="cp852")

        await printer.print_text_image(
            "Příliš žluťoučký kůň\núpěl ďábelské ódy",
            font_size=28, align=Align.LEFT,
        )
        await printer.feed(4)
    print("Done, disconnected.")


def _demo_spp(address: str) -> None:
    """Self-contained SPP demo (Linux only)."""
    printer = GoojPrtPT210()
    print(f"Connecting (SPP) to {address} ...")
    printer.connect_spp(address)
    print("Connected.")
    try:
        printer.initialize_spp()
        printer.print_text_spp("SPP print test", align=Align.CENTER, bold=True)
        printer.feed_spp(4)
    finally:
        with contextlib.suppress(Exception):
            printer.disconnect_spp()
    print("Done, disconnected.")


async def _run_test(address: str, test_string: str) -> None:
    """Probe the firmware's code-page table using :meth:`probe_charsets`."""
    async with _connected(address) as printer:
        print("Running code-page probe...\n")
        await printer.probe_charsets(test_string)
    print("Probe complete, disconnected.")


async def _run_test_cp1250(address: str, test_string: str) -> None:
    """Native ESC/POS print-quality test for the CP1250 code page.

    Emits five variants of the input text (Font A/B, bold, raised heating
    energy) so the paper output can be compared side by side.
    """
    from goojprt import commands

    def label(text: str) -> bytes:
        """Return an ASCII label used to separate variants on the paper."""
        return f"--- {text} ---\n".encode("ascii", errors="replace")

    encoded = test_string.encode("cp1250", errors="replace")

    async with _connected(address) as printer:
        print("Running CP1250 quality test...\n")
        await printer._ble.write(commands.charset(CodePage.WPC1250))

        # 1) Normal
        await printer._ble.write(label("1) Font A, normal"))
        await printer._ble.write(commands.font(font_b=False))
        await printer._ble.write(commands.bold(False))
        await printer._ble.write(encoded + b"\n")

        # 2) Bold
        await printer._ble.write(label("2) Font A, bold"))
        await printer._ble.write(commands.bold(True))
        await printer._ble.write(encoded + b"\n")
        await printer._ble.write(commands.bold(False))

        # 3) Font B
        await printer._ble.write(label("3) Font B, normal"))
        await printer._ble.write(commands.font(font_b=True))
        await printer._ble.write(encoded + b"\n")
        await printer._ble.write(commands.font(font_b=False))

        # 4) Font A with higher heating energy
        await printer._ble.write(label("4) Font A + energy 120"))
        await printer._ble.write(commands.energy(dots=7, heating=120, interval=2))
        await printer._ble.write(encoded + b"\n")

        # 5) Bold with higher heating energy
        await printer._ble.write(label("5) Bold + energy 120"))
        await printer._ble.write(commands.bold(True))
        await printer._ble.write(encoded + b"\n")
        await printer._ble.write(commands.bold(False))

        # Restore default energy and feed paper out.
        await printer._ble.write(commands.energy(dots=7, heating=80, interval=2))
        await printer.feed(4)
    print("CP1250 test complete, disconnected.")


def _density_arg(value: str) -> "str | int":
    """``--density`` value: a preset name or a number 0-255."""
    level: "str | int" = int(value) if value.isdigit() else value
    try:
        resolve_density(level)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return level


def build_parser() -> argparse.ArgumentParser:
    """Build the ``argparse`` parser with every supported CLI flag."""
    parser = argparse.ArgumentParser(
        prog="goojprt",
        description="GoojPrt PT-210 Bluetooth driver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Find the printer's address (a UUID on macOS), then use it
  python3 -m goojprt --scan
  export {ADDRESS_ENV}=<address>        # optional: then the address can be left out

  # BLE demo print
  python3 -m goojprt <addr>

  # Bitmap text with antialiasing
  python3 -m goojprt <addr> --print-image "Příliš žluťoučký kůň"
  python3 -m goojprt <addr> --print-image "Headline" --font-size 48 --no-dither

  # An image file, scaled down to the paper
  python3 -m goojprt <addr> --print-file photo.jpg
  python3 -m goojprt <addr> --print-file logo.png --fit width --density dark

  # PDF417 barcode
  python3 -m goojprt <addr> --pdf417 "1234567890"
  python3 -m goojprt <addr> --pdf417 "data" --pdf417-scale 3 --pdf417-columns 7

  # Template, rendered to a PNG instead of printed (no printer needed)
  python3 -m goojprt --template examples/receipt.toml --preview receipt.png

  # Code-page probe
  python3 -m goojprt <addr> --test
  python3 -m goojprt <addr> --test --test-string "Custom text"
        """,
    )

    parser.add_argument(
        "address", nargs="?", default=None,
        help=f"Bluetooth address / UUID of the printer (default: ${ADDRESS_ENV})",
    )
    parser.add_argument(
        "mode", nargs="?", default="ble", choices=["ble", "spp"],
        help="Transport: ble (default) or spp",
    )

    g_scan = parser.add_argument_group("Finding the printer (--scan)")
    g_scan.add_argument("--scan", action="store_true",
                        help="List nearby Bluetooth LE devices and exit")
    g_scan.add_argument("--scan-timeout", type=float, default=5.0, metavar="SECONDS",
                        help="Scan duration (default: 5)")
    g_scan.add_argument("--scan-all", action="store_true",
                        help="Include devices that advertise no name")

    g_out = parser.add_argument_group("Output options (--print-image, --print-file, --pdf417, --template)")
    g_out.add_argument("--preview", metavar="OUT.png",
                       help="Render into this PNG file instead of printing; no printer or "
                            "address needed. Native text and QR codes show up as dashed notes.")
    g_out.add_argument("--density", type=_density_arg, metavar="light|normal|dark|0-255",
                       help="Print darkness (ESC 7 heating time); presets are uncalibrated "
                            "starting points")

    g_img = parser.add_argument_group("Bitmap text printing (--print-image)")
    g_img.add_argument("--print-image", metavar="TEXT",
                       help="Print TEXT as a bitmap image (supports diacritics)")
    g_img.add_argument("--font-size", type=int, default=24, metavar="PT",
                       help="Font size in points (default: 24)")
    g_img.add_argument("--font", metavar="PATH",
                       help="Path to a .ttf/.ttc file (default: system font)")
    g_img.add_argument("--align", choices=["left", "center", "right"], default="left",
                       help="Alignment of text, or of an image narrower than the paper "
                            "(default: left)")
    g_img.add_argument("--supersample", type=int, default=3, metavar="N",
                       help="Antialiasing oversampling factor 1–4 (default: 3)")
    g_img.add_argument("--no-dither", action="store_true",
                       help="Disable Floyd–Steinberg dithering, use pure threshold")
    g_img.add_argument("--threshold", type=int, default=140, metavar="0-255",
                       help="Threshold for --no-dither (default: 140)")

    g_file = parser.add_argument_group("Image file (--print-file)")
    g_file.add_argument("--print-file", metavar="PATH",
                        help="Print an image file (also uses --align, --no-dither, --threshold)")
    g_file.add_argument("--fit", choices=FIT_MODES, default="shrink",
                        help="shrink: scale down to the paper when wider (default); "
                             "width: fill the paper; none: keep the size, cut off what is wider")
    g_file.add_argument("--scale", type=float, default=1.0, metavar="FACTOR",
                        help="Size factor applied on top of --fit (default: 1.0)")

    g_pdf = parser.add_argument_group("PDF417 barcode (--pdf417)")
    g_pdf.add_argument("--pdf417", metavar="DATA",
                       help="Print a PDF417 barcode encoding DATA")
    g_pdf.add_argument("--pdf417-scale", type=int, default=2, metavar="N",
                       help="Module width in pixels (default: 2)")
    g_pdf.add_argument("--pdf417-row-height", type=int, default=5, metavar="N",
                       help="Row height in modules (default: 5)")
    g_pdf.add_argument("--pdf417-min-rows", type=int, default=None, metavar="N",
                       help="Minimum row count (auto-decreases column count)")
    g_pdf.add_argument("--pdf417-columns", type=int, default=5, metavar="N",
                       help="Data column count 1–30 (default: 5)")

    g_tmpl = parser.add_argument_group("TOML template (--template)")
    g_tmpl.add_argument("--template", metavar="FILE",
                        help="Path to a .toml template (see examples/)")
    g_tmpl.add_argument("--var", action="append", metavar="KEY=VALUE", default=[],
                        help="Template variable (may be repeated)")

    g_test = parser.add_argument_group("Code-page probe (--test)")
    g_test.add_argument("--test", action="store_true",
                        help="Probe each code page and print a bitmap reference")
    g_test.add_argument("--test-string",
                        default="Příliš žluťoučký kůň úpěl ďábelské ódy",
                        metavar="TEXT", help="Text used by --test")
    g_test.add_argument("--test-cp1250", action="store_true",
                        help="CP1250 quality test: 5 variants (Font A/B, bold, energy)")

    return parser


def _resolve_target(args: argparse.Namespace) -> tuple[str | None, str]:
    """Work out the printer address and transport from the arguments and the environment.

    An explicit address wins over :data:`ADDRESS_ENV`. ``goojprt spp`` (a lone
    transport name) means "use the address from the environment".
    """
    address, mode = args.address, args.mode
    if address in ("ble", "spp") and mode == "ble":
        address, mode = None, address
    return address or os.environ.get(ADDRESS_ENV) or None, mode


def _prepare_file(args: argparse.Namespace):
    """Open ``--print-file`` and run the 1-bit pipeline; ``SystemExit`` on a bad file."""
    from PIL import Image

    from goojprt.rendering.image_print import prepare_image

    try:
        with Image.open(args.print_file) as source:
            return prepare_image(
                source,
                scale=args.scale,
                fit=args.fit,
                threshold=args.threshold,
                dither=not args.no_dither,
                align=args.align,
            )
    except (OSError, ValueError) as exc:
        sys.exit(f"goojprt: cannot use {args.print_file!r}: {exc}")


def main() -> None:
    """Entry point. Parses ``argv`` and dispatches to the selected command."""
    parser = build_parser()
    args = parser.parse_args()
    align_map = {"left": Align.LEFT, "center": Align.CENTER, "right": Align.RIGHT}

    if args.scan:
        asyncio.run(_scan(args.scan_timeout, args.scan_all))
        return

    address, mode = _resolve_target(args)
    args.address, args.mode = address, mode

    renders_bitmaps = bool(args.template or args.print_image or args.print_file or args.pdf417)
    if args.preview is not None and not renders_bitmaps:
        parser.error("--preview works with --template, --print-image, --print-file or --pdf417")
    if args.density is not None and not renders_bitmaps:
        parser.error("--density works with --template, --print-image, --print-file or --pdf417")
    if args.preview is not None and args.mode == "spp":
        parser.error("--preview cannot be combined with the spp transport")
    if address is None and args.preview is None:
        parser.error(f"a printer address is required: pass it as the first argument or set "
                     f"{ADDRESS_ENV} (use --scan to find it)")

    session = {"preview": args.preview, "density": args.density}

    if args.template:
        extra = {}
        for pair in args.var:
            if "=" in pair:
                k, v = pair.split("=", 1)
                extra[k.strip()] = v.strip()
        try:
            asyncio.run(print_template(
                args.address, args.template, extra or None,
                density=args.density, preview=args.preview,
            ))
        except TemplateError as exc:
            sys.exit(f"goojprt: {exc}")

    elif args.test:
        asyncio.run(_run_test(args.address, args.test_string))

    elif args.test_cp1250:
        asyncio.run(_run_test_cp1250(args.address, args.test_string))

    elif args.print_image:
        async def _cmd() -> None:
            """Bitmap text print: connect, initialise, print, disconnect."""
            async with _connected(args.address, **session) as printer:
                await printer.print_text_image(
                    args.print_image,
                    font_size=args.font_size,
                    font_path=args.font,
                    align=align_map[args.align],
                    supersample=args.supersample,
                    dither=not args.no_dither,
                    threshold=args.threshold,
                )
                await printer.feed(3)
        asyncio.run(_cmd())

    elif args.print_file:
        image = _prepare_file(args)     # a bad file must fail before the printer is touched

        async def _cmd() -> None:
            """Image file print: connect, initialise, print, disconnect."""
            async with _connected(args.address, **session) as printer:
                await printer.print_image(image)
                await printer.feed(3)
        asyncio.run(_cmd())

    elif args.pdf417:
        async def _cmd() -> None:
            """PDF417 print: connect, initialise, print, disconnect."""
            async with _connected(args.address, **session) as printer:
                await printer.print_pdf417(
                    args.pdf417,
                    scale=args.pdf417_scale,
                    row_height=args.pdf417_row_height,
                    columns=args.pdf417_columns,
                    min_rows=args.pdf417_min_rows,
                )
                await printer.feed(3)
        asyncio.run(_cmd())

    elif args.mode == "ble":
        asyncio.run(_demo_ble(args.address))

    else:
        _demo_spp(args.address)
