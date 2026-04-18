"""TOML template engine for the GoojPrt PT-210.

Lets callers define a print job as a list of items in a ``.toml`` file,
with dynamic variables substituted before printing. A job is printed
by calling :func:`print_template` — the function loads the file,
expands variables, connects over BLE and issues the matching SDK calls.

Supported item types (see :func:`print_template` for the full dispatch
table): ``text_image``, ``text``, ``pdf417``, ``qr``, ``line``, ``feed``,
``cut``, ``grid``, ``ekg``. Unknown types produce a warning on stdout
and are skipped.
"""

import datetime
import re
import secrets
import tomllib

from goojprt.enums import Align, TextSize
from goojprt.printer import GoojPrtPT210


def random_password(length: int) -> str:
    """Generate a human-readable random password.

    Uses :func:`secrets.choice` and excludes characters that can be
    confused visually (``0`` vs ``O``, ``1`` vs ``l`` vs ``I``).

    :param length: Desired password length in characters.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_vars(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build the built-in variable table (date, time, expiries, passwords).

    Time-related variables (values reflect "now" at call time):

    * ``{{date}}``        — today's date (``02.04.2026``)
    * ``{{date_iso}}``    — ISO date (``2026-04-02``)
    * ``{{time}}``        — current time (``14:35``)
    * ``{{time_full}}``   — current time with seconds
    * ``{{datetime}}``    — date + time
    * ``{{weekday}}``     — Czech weekday name (``Středa``)
    * ``{{week}}``        — ISO week number
    * ``{{expire_1h}}``   — time + 1 hour
    * ``{{expire_2h}}``   — time + 2 hours
    * ``{{expire_4h}}``   — time + 4 hours
    * ``{{expire_24h}}``  — date + time in 24 hours

    Passwords (generated once, identical inside a single template run):

    * ``{{password_8}}``  — 8 characters
    * ``{{password_12}}`` — 12 characters
    * ``{{password_16}}`` — 16 characters

    :param extra: User-supplied variables (e.g. from the CLI ``--var``
        flag). They override built-ins when names collide.
    """
    now = datetime.datetime.now()
    fmt = "%H:%M"
    weekdays = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
    built_in: dict[str, str] = {
        "date":       now.strftime("%d.%m.%Y"),
        "date_iso":   now.strftime("%Y-%m-%d"),
        "time":       now.strftime(fmt),
        "time_full":  now.strftime("%H:%M:%S"),
        "datetime":   now.strftime(f"%d.%m.%Y {fmt}"),
        "weekday":    weekdays[now.weekday()],
        "week":       now.strftime("%V"),
        "expire_1h":  (now + datetime.timedelta(hours=1)).strftime(fmt),
        "expire_2h":  (now + datetime.timedelta(hours=2)).strftime(fmt),
        "expire_4h":  (now + datetime.timedelta(hours=4)).strftime(fmt),
        "expire_24h": (now + datetime.timedelta(hours=24)).strftime(f"%d.%m.%Y {fmt}"),
        "password_8":  random_password(8),
        "password_12": random_password(12),
        "password_16": random_password(16),
    }
    if extra:
        built_in.update(extra)
    return built_in


def substitute(text: str, variables: dict[str, str]) -> str:
    """Replace ``{{key}}`` placeholders with the matching value.

    Unknown keys are left verbatim.
    """
    def replace(m: re.Match) -> str:
        """Look up a single variable; return the original placeholder on miss."""
        key = m.group(1).strip()
        if key in variables:
            return variables[key]
        return m.group(0)
    return re.sub(r"\{\{(.+?)\}\}", replace, text)


def substitute_deep(obj, variables: dict[str, str]):
    """Recursively substitute ``{{variables}}`` inside any string within ``obj``."""
    if isinstance(obj, str):
        return substitute(obj, variables)
    if isinstance(obj, dict):
        return {k: substitute_deep(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_deep(v, variables) for v in obj]
    return obj


async def print_template(
    address: str,
    path: str,
    extra_vars: dict[str, str] | None = None,
) -> None:
    """Load a TOML template, substitute variables, connect via BLE and print.

    Supported item types: ``text_image``, ``text``, ``pdf417``, ``qr``,
    ``line``, ``feed``, ``cut``, ``grid``, ``ekg``. Unknown types print
    a warning on stdout and are skipped.

    :param address: Bluetooth address / UUID of the printer.
    :param path: Filesystem path to a ``.toml`` template.
    :param extra_vars: Additional variables (e.g. ``--var name=Filip``).
    """
    with open(path, "rb") as f:
        tmpl = tomllib.load(f)

    variables = build_vars(extra_vars)

    items = tmpl.get("items", [])
    if not items:
        print("Template contains no items.")
        return

    align_map = {"left": Align.LEFT, "center": Align.CENTER, "right": Align.RIGHT}
    size_map = {
        "normal":        TextSize.NORMAL,
        "double_height": TextSize.DOUBLE_HEIGHT,
        "double_width":  TextSize.DOUBLE_WIDTH,
        "double_both":   TextSize.DOUBLE_BOTH,
    }

    printer = GoojPrtPT210()
    print(f"Connecting to {address} ...")
    await printer.connect_ble(address)
    print(f"Connected. Printing template: {path}\n")
    await printer.initialize()

    for i, item in enumerate(items):
        kind = item.get("type", "")
        item = substitute_deep(item, variables)
        print(f"  [{i+1}/{len(items)}] {kind}")

        if kind == "text_image":
            await printer.print_text_image(
                item["text"],
                font_size=item.get("font_size", 24),
                font_path=item.get("font", None),
                align=align_map.get(item.get("align", "left"), Align.LEFT),
                line_spacing=item.get("line_spacing", 6),
                padding=item.get("padding", 8),
                supersample=item.get("supersample", 3),
                dither=item.get("dither", True),
                threshold=item.get("threshold", 140),
            )
        elif kind == "text":
            await printer.print_text(
                item["text"],
                align=align_map.get(item.get("align", "left"), Align.LEFT),
                bold=item.get("bold", False),
                underline=item.get("underline", False),
                size=size_map.get(item.get("size", "normal"), TextSize.NORMAL),
                newline=item.get("newline", True),
                encoding=item.get("encoding", "gb2312"),
            )
        elif kind == "pdf417":
            await printer.print_pdf417(
                item["data"],
                align=align_map.get(item.get("align", "center"), Align.CENTER),
                scale=item.get("scale", 2),
                row_height=item.get("row_height", 5),
                columns=item.get("columns", 5),
                padding=item.get("padding", 10),
                min_rows=item.get("min_rows", None),
            )
        elif kind == "qr":
            await printer.print_qr(
                item["data"],
                size=item.get("size", 6),
                align=align_map.get(item.get("align", "center"), Align.CENTER),
                error_correction=item.get("error_correction", 1),
            )
        elif kind == "line":
            await printer.print_line(char=item.get("char", "-"))
        elif kind == "feed":
            await printer.feed(item.get("lines", 3))
        elif kind == "cut":
            await printer.cut()
        elif kind == "grid":
            await printer.print_grid(
                item.get("columns", []),
                font_size=item.get("font_size", 22),
                font_path=item.get("font", None),
                padding=item.get("padding", 6),
                supersample=item.get("supersample", 3),
                dither=item.get("dither", False),
                threshold=item.get("threshold", 128),
            )
        elif kind == "ekg":
            await printer.print_ekg(
                beats=item.get("beats", 4),
                height_px=item.get("height", 160),
                line_width=item.get("line_width", 2),
                grid=item.get("grid", True),
                grid_step_px=item.get("grid_step", 32),
                amplitude=item.get("amplitude", 0.82),
                portrait=item.get("portrait", False),
                px_per_beat=item.get("px_per_beat", 240),
            )
        else:
            print(f"    ! Unknown item type: '{kind}', skipping.")

    await printer.disconnect()
    print("\nDone, disconnected.")
