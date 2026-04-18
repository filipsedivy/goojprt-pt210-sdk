"""Command-line interface for the GoojPrt PT-210 SDK.

Entry point: ``python -m goojprt <address> [flags]``. Flags are kept
stable with the historic standalone ``goojprt.py`` script so existing
shell snippets keep working.
"""

import argparse
import asyncio

from goojprt.enums import Align, CodePage, TextSize
from goojprt.printer import GoojPrtPT210
from goojprt.template import print_template


async def _demo_ble(address: str) -> None:
    """Self-contained BLE demo: text, QR, PDF417, diacritics (bitmap)."""
    printer = GoojPrtPT210()
    print(f"Connecting to {address} ...")
    await printer.connect_ble(address)
    print("Connected.")

    await printer.initialize()
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

    await printer.disconnect()
    print("Done, disconnected.")


def _demo_spp(address: str) -> None:
    """Self-contained SPP demo (Linux only)."""
    printer = GoojPrtPT210()
    print(f"Connecting (SPP) to {address} ...")
    printer.connect_spp(address)
    print("Connected.")

    printer.initialize_spp()
    printer.print_text_spp("SPP print test", align=Align.CENTER, bold=True)
    printer.feed_spp(4)

    printer.disconnect_spp()
    print("Done, disconnected.")


async def _run_test(address: str, test_string: str) -> None:
    """Probe the firmware's code-page table using :meth:`probe_charsets`."""
    printer = GoojPrtPT210()
    print(f"Connecting to {address} ...")
    await printer.connect_ble(address)
    print("Connected. Running code-page probe...\n")

    await printer.initialize()
    await printer.probe_charsets(test_string)

    await printer.disconnect()
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

    printer = GoojPrtPT210()
    print(f"Connecting to {address} ...")
    await printer.connect_ble(address)
    print("Connected. Running CP1250 quality test...\n")

    encoded = test_string.encode("cp1250", errors="replace")

    await printer.initialize()
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
    await printer.disconnect()
    print("CP1250 test complete, disconnected.")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``argparse`` parser with every supported CLI flag."""
    parser = argparse.ArgumentParser(
        prog="goojprt",
        description="GoojPrt PT-210 Bluetooth driver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # BLE demo print
  python3 -m goojprt <addr>

  # Bitmap text with antialiasing
  python3 -m goojprt <addr> --print-image "Příliš žluťoučký kůň"
  python3 -m goojprt <addr> --print-image "Headline" --font-size 48 --no-dither

  # PDF417 barcode
  python3 -m goojprt <addr> --pdf417 "1234567890"
  python3 -m goojprt <addr> --pdf417 "data" --pdf417-scale 3 --pdf417-columns 7

  # Code-page probe
  python3 -m goojprt <addr> --test
  python3 -m goojprt <addr> --test --test-string "Custom text"
        """,
    )

    parser.add_argument("address", help="Bluetooth address / UUID of the printer")
    parser.add_argument(
        "mode", nargs="?", default="ble", choices=["ble", "spp"],
        help="Transport: ble (default) or spp",
    )

    g_img = parser.add_argument_group("Bitmap text printing (--print-image)")
    g_img.add_argument("--print-image", metavar="TEXT",
                       help="Print TEXT as a bitmap image (supports diacritics)")
    g_img.add_argument("--font-size", type=int, default=24, metavar="PT",
                       help="Font size in points (default: 24)")
    g_img.add_argument("--font", metavar="PATH",
                       help="Path to a .ttf/.ttc file (default: system font)")
    g_img.add_argument("--align", choices=["left", "center", "right"], default="left",
                       help="Text alignment (default: left)")
    g_img.add_argument("--supersample", type=int, default=3, metavar="N",
                       help="Antialiasing oversampling factor 1–4 (default: 3)")
    g_img.add_argument("--no-dither", action="store_true",
                       help="Disable Floyd–Steinberg dithering, use pure threshold")
    g_img.add_argument("--threshold", type=int, default=140, metavar="0-255",
                       help="Threshold for --no-dither (default: 140)")

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


def main() -> None:
    """Entry point. Parses ``argv`` and dispatches to the selected command."""
    parser = build_parser()
    args = parser.parse_args()
    align_map = {"left": Align.LEFT, "center": Align.CENTER, "right": Align.RIGHT}

    if args.template:
        extra = {}
        for pair in args.var:
            if "=" in pair:
                k, v = pair.split("=", 1)
                extra[k.strip()] = v.strip()
        asyncio.run(print_template(args.address, args.template, extra or None))

    elif args.test:
        asyncio.run(_run_test(args.address, args.test_string))

    elif args.test_cp1250:
        asyncio.run(_run_test_cp1250(args.address, args.test_string))

    elif args.print_image:
        async def _cmd() -> None:
            """Bitmap text print: connect, initialise, print, disconnect."""
            printer = GoojPrtPT210()
            await printer.connect_ble(args.address)
            await printer.initialize()
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
            await printer.disconnect()
        asyncio.run(_cmd())

    elif args.pdf417:
        async def _cmd() -> None:
            """PDF417 print: connect, initialise, print, disconnect."""
            printer = GoojPrtPT210()
            await printer.connect_ble(args.address)
            await printer.initialize()
            await printer.print_pdf417(
                args.pdf417,
                scale=args.pdf417_scale,
                row_height=args.pdf417_row_height,
                columns=args.pdf417_columns,
                min_rows=args.pdf417_min_rows,
            )
            await printer.feed(3)
            await printer.disconnect()
        asyncio.run(_cmd())

    elif args.mode == "ble":
        asyncio.run(_demo_ble(args.address))

    else:
        _demo_spp(args.address)
