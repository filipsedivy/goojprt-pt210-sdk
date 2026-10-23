"""TOML template engine for the GoojPrt PT-210.

Lets callers define a print job as a list of items in a ``.toml`` file,
with dynamic variables substituted before printing. A job is printed
by calling :func:`print_template` — the function loads the file,
expands variables, connects over BLE and issues the matching SDK calls.

Supported item types are listed in :data:`ITEM_TYPES`; see
:func:`print_template` for the dispatch table. Unknown types produce a
warning on stdout and are skipped.
"""

import asyncio
import datetime
import re
import secrets
import tomllib
from pathlib import Path

from goojprt import commands
from goojprt.encoding import CODEPAGE_TO_ENCODING
from goojprt.enums import Align, CodePage, TextSize
from goojprt.profile import TextProfile
from goojprt.printer import GoojPrtPT210, disconnect_quietly

#: Item ``type`` values understood by :func:`print_template`.
ITEM_TYPES = frozenset({
    "text_image", "text", "pdf417", "qr", "line", "feed", "cut", "grid", "ekg",
    "charset", "chinese_mode", "image", "density", "codepage",
})


class TemplateError(ValueError):
    """A template cannot be printed (for example an image that cannot be read)."""


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


def _prepare_image_item(index: int, item: dict, base_dir: Path):
    """Open and prepare the picture of one ``image`` item (blocking).

    :raises TemplateError: When the path is missing, the file cannot be read
        or an option is invalid.
    """
    from PIL import Image

    from goojprt.rendering.image_print import prepare_image

    name = item.get("path")
    if not name:
        raise TemplateError(f"item {index + 1} (image): missing 'path'")
    file = Path(name)
    if not file.is_absolute():
        file = base_dir / file
    try:
        with Image.open(file) as source:
            return prepare_image(
                source,
                rotate=item.get("rotate", 0),
                scale=item.get("scale", 1.0),
                fit=item.get("fit", "shrink"),
                brightness=item.get("brightness", 1.0),
                contrast=item.get("contrast", 1.0),
                threshold=item.get("threshold", 128),
                dither=item.get("dither", True),
                align=item.get("align", "center"),
            )
    except OSError as exc:  # includes FileNotFoundError and PIL.UnidentifiedImageError
        raise TemplateError(f"item {index + 1} (image): cannot read {str(file)!r}: {exc}") from exc
    except ValueError as exc:
        raise TemplateError(f"item {index + 1} (image): {exc}") from exc


def _codepage_profile(item: dict) -> TextProfile:
    """The profile a ``codepage`` item stands for.

    ``code_page`` is a :class:`~goojprt.enums.CodePage` name (``"PC852"``) or a
    table number; ``encoding`` defaults to the codec known for the table and
    ``chinese_mode_off`` (send ``FS .`` first) to ``true``.

    :raises ValueError: For an unknown name, a table without a known codec
        and no ``encoding``, or an invalid value.
    """
    page = item.get("code_page")
    if isinstance(page, str):
        try:
            page = int(CodePage[page.upper()])
        except KeyError:
            raise ValueError(f"unknown code page {page!r} (known: {', '.join(cp.name for cp in CodePage)})") from None
    if not isinstance(page, int) or isinstance(page, bool):
        raise ValueError("code_page is required (a CodePage name or a table number)")
    encoding = item.get("encoding") or CODEPAGE_TO_ENCODING.get(page)
    if encoding is None:
        raise ValueError(f"no codec is known for code page {page}; add encoding = \"...\"")
    return TextProfile(page, encoding, item.get("chinese_mode_off", True))


def _validate_codepage_items(items: list[dict]) -> None:
    """Reject bad ``codepage`` items before the printer is touched."""
    for i, item in enumerate(items):
        if item.get("type") == "codepage":
            try:
                _codepage_profile(item)
            except ValueError as exc:
                raise TemplateError(f"item {i + 1} (codepage): {exc}") from exc


def _density_of(item: dict) -> "str | int":
    """The ``level`` / ``heating`` setting of a ``density`` item."""
    return item.get("level", item.get("heating", "normal"))


def _validate_density_items(items: list[dict]) -> None:
    """Reject bad ``density`` items before the printer is touched."""
    for i, item in enumerate(items):
        if item.get("type") != "density":
            continue
        try:
            commands.energy(
                dots=item.get("dots", 7),
                heating=commands.resolve_density(_density_of(item)),
                interval=item.get("interval", 2),
            )
        except (ValueError, TypeError) as exc:
            raise TemplateError(f"item {i + 1} (density): {exc}") from exc


async def _prepare_images(items: list[dict], base_dir: Path) -> dict[int, object]:
    """Prepare every ``image`` item up front, keyed by item index.

    Done before connecting, so a missing logo fails before any paper is used.
    """
    return {
        i: await asyncio.to_thread(_prepare_image_item, i, item, base_dir)
        for i, item in enumerate(items)
        if item.get("type") == "image"
    }


async def print_template(
    address: str | None,
    path: str,
    extra_vars: dict[str, str] | None = None,
    *,
    density: "str | int | None" = None,
    preview: "str | None" = None,
    profile: TextProfile | None = None,
) -> None:
    """Load a TOML template, substitute variables, connect via BLE and print.

    Supported item types: see :data:`ITEM_TYPES`. ``charset`` selects a
    code page by :class:`~goojprt.enums.CodePage` name (``code_page =
    "PC852"``) and ``chinese_mode`` toggles the double-byte mode
    (``enabled = false``); both affect the native ``text`` items that
    follow, and so does ``codepage`` (``code_page = "PC852"`` or a table number;
    optional ``encoding`` and ``chinese_mode_off``), which selects the table,
    cancels the Chinese mode and makes ``text`` items encode for it — the
    one-item way to print native Czech. A ``text`` item with ``auto = true``
    prints natively when the active table can show the text and as a bitmap
    otherwise. ``density`` sets the print darkness (``level`` = ``light`` /
    ``normal`` / ``dark``, or ``heating`` = 0–255). Unknown types print a warning on stdout and are skipped.

    An ``image`` item prints a picture (``path`` is relative to the template
    file; ``fit``, ``scale``, ``align``, ``dither``, ``threshold``,
    ``brightness``, ``contrast`` and ``rotate`` as in
    :func:`~goojprt.rendering.image_print.prepare_image`). Pictures are
    opened before the printer is touched.

    :param address: Bluetooth address / UUID of the printer; not needed (and
        not used) with ``preview``.
    :param path: Filesystem path to a ``.toml`` template.
    :param extra_vars: Additional variables (e.g. ``--var name=Filip``).
    :param density: Print darkness applied right after the printer is
        initialised (see :meth:`~goojprt.printer.GoojPrtPT210.set_density`);
        a ``density`` item (``level = "dark"`` or ``heating = 120``) in the
        template overrides it from that point on.
    :param profile: Native text profile applied right after the printer is
        initialised (see :meth:`~goojprt.printer.GoojPrtPT210.apply_profile`),
        so ``text`` items with diacritics need no ``encoding``. A ``codepage``
        item overrides it from that point on.
    :param preview: Render into this PNG file instead of printing — no
        printer is needed. Bitmap items are drawn as they would print;
        native ``text`` and ``qr`` items appear as dashed notes only.
    :raises TemplateError: When an ``image`` or ``density`` item, or
        ``density``, is invalid.
    :raises ValueError: When neither ``address`` nor ``preview`` is given.
    """
    if address is None and preview is None:
        raise ValueError("print_template needs an address, or preview= to render without a printer")
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

    items = [substitute_deep(item, variables) for item in items]
    if density is not None:
        try:
            commands.resolve_density(density)
        except ValueError as exc:
            raise TemplateError(f"density: {exc}") from exc
    _validate_density_items(items)
    _validate_codepage_items(items)
    images = await _prepare_images(items, Path(path).resolve().parent)

    printer = GoojPrtPT210()
    transport = None
    if preview is None:
        print(f"Connecting to {address} ...")
        await printer.connect_ble(address)
        print(f"Connected. Printing template: {path}\n")
    else:
        transport = printer.connect_preview()
        print(f"Rendering template {path} into {preview} ...\n")
    try:
        await printer.initialize()
        if density is not None:
            await printer.set_density(density)
        if profile is not None:
            await printer.apply_profile(profile)

        for i, item in enumerate(items):
            kind = item.get("type", "")
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
                    wrap=item.get("wrap", True),
                )
            elif kind == "image":
                await printer.print_image(images[i])
            elif kind == "text" and item.get("auto", False):
                await printer.print_text_auto(
                    item["text"],
                    align=align_map.get(item.get("align", "left"), Align.LEFT),
                    bold=item.get("bold", False),
                    underline=item.get("underline", False),
                    size=size_map.get(item.get("size", "normal"), TextSize.NORMAL),
                    font_size=item.get("font_size", 24),
                )
            elif kind == "text":
                await printer.print_text(
                    item["text"],
                    align=align_map.get(item.get("align", "left"), Align.LEFT),
                    bold=item.get("bold", False),
                    underline=item.get("underline", False),
                    size=size_map.get(item.get("size", "normal"), TextSize.NORMAL),
                    newline=item.get("newline", True),
                    encoding=item.get("encoding"),
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
            elif kind == "charset":
                name = str(item.get("code_page", ""))
                try:
                    code_page = CodePage[name.upper()]
                except KeyError:
                    known = ", ".join(cp.name for cp in CodePage)
                    print(f"    ! Unknown code page '{name}' (known: {known}), skipping.")
                    continue
                await printer.set_charset(code_page)
            elif kind == "density":
                await printer.set_density(
                    _density_of(item),
                    dots=item.get("dots", 7),
                    interval=item.get("interval", 2),
                )
            elif kind == "codepage":
                await printer.apply_profile(_codepage_profile(item))
            elif kind == "chinese_mode":
                await printer.set_chinese_mode(bool(item.get("enabled", False)))
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
        if transport is not None and preview is not None:
            transport.save(preview)
            print(f"\nPreview saved to {preview}: {transport.summary()}")
    finally:
        await disconnect_quietly(printer)
    if transport is None:
        print("\nDone, disconnected.")
