"""Command-line entry point: ``goojprt-server`` / ``python -m goojprt_server``.

When no BLE address is supplied and stdin is a TTY, the CLI launches an
interactive scan wizard: it discovers nearby BLE devices with Rich
progress feedback, shows a numbered table, and lets the operator pick.
Non-interactive runs (CI, systemd) fall back to the usual error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import Optional

from goojprt_server.config import Settings


_SCAN_TIMEOUT_S = 8.0
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                      r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="goojprt-server",
        description="GoojPrt PT-210 print server (BLE, single printer).",
    )
    p.add_argument("ble_address", nargs="?",
                   help="BLE address of the PT-210 (overrides GOOJPRT_BLE_ADDRESS)")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--log-level", choices=["debug", "info", "warning"], default=None)
    p.add_argument("--log-json", action="store_true")
    p.add_argument("--queue-max-size", type=int, default=None)
    p.add_argument("--reconnect-interval-s", type=float, default=None)
    p.add_argument("--reconnect-job-wait", type=float, default=None,
                   dest="reconnect_job_wait_s",
                   help="Seconds a queued job waits for reconnect before failing (default 60)")
    p.add_argument("--reconnect-log-interval", type=float, default=None,
                   dest="reconnect_log_interval_s",
                   help="Seconds between 'still reconnecting' log messages (default 30)")
    p.add_argument("--scan-timeout", type=float, default=_SCAN_TIMEOUT_S,
                   help=f"BLE scan timeout in seconds (default {_SCAN_TIMEOUT_S})")
    p.add_argument("--no-wizard", action="store_true",
                   help="Disable the interactive scan wizard even on a TTY")
    p.add_argument("--no-dashboard", action="store_true",
                   help="Disable the interactive live dashboard; fall back to streaming logs")
    p.add_argument("--log-file", default=None,
                   help="Path to a rotating server log file (default: platform-specific)")
    p.add_argument("--no-log-file", action="store_true",
                   help="Disable file logging even when the dashboard is active")
    return p


def _collect_overrides(ns: argparse.Namespace) -> dict:
    overrides: dict = {}
    if ns.ble_address:
        overrides["ble_address"] = ns.ble_address
    for src, dst in (
        ("host", "host"), ("port", "port"),
        ("log_level", "log_level"),
        ("queue_max_size", "queue_max_size"),
        ("reconnect_interval_s", "reconnect_interval_s"),
        ("reconnect_job_wait_s", "reconnect_job_wait_s"),
        ("reconnect_log_interval_s", "reconnect_log_interval_s"),
    ):
        v = getattr(ns, src)
        if v is not None:
            overrides[dst] = v
    if ns.log_json:
        overrides["log_json"] = True
    if ns.no_dashboard:
        overrides["no_dashboard"] = True
    if ns.log_file is not None:
        from pathlib import Path
        overrides["log_file"] = Path(ns.log_file)
    if ns.no_log_file:
        overrides["no_log_file"] = True
    return overrides


def settings_from_args(ns: argparse.Namespace) -> Settings:
    """Build :class:`Settings` from parsed args without any interactive prompts.

    Kept deliberately side-effect-free so tests can exercise it without
    touching BLE or stdin.
    """
    overrides = _collect_overrides(ns)
    if "ble_address" not in overrides and not os.environ.get("GOOJPRT_BLE_ADDRESS"):
        raise SystemExit(
            "ble_address is required (positional arg or GOOJPRT_BLE_ADDRESS env)"
        )
    return Settings(**overrides)


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _looks_like_pt210(device: dict) -> bool:
    name = (device.get("name") or "").upper()
    return "PT" in name or "GOOJPRT" in name or "PRT" in name


async def _scan_devices(timeout: float) -> list[dict]:
    """Run a BLE scan with a Rich progress spinner; return the device list."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    from goojprt import GoojPrtPT210

    console = Console()
    printer = GoojPrtPT210()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]Scanning BLE devices…[/bold cyan]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("scan", total=None)
        devices = await printer.scan_ble(timeout=timeout)
    return devices


def _render_device_table(devices: list[dict]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(
        title=f"Found {len(devices)} BLE device(s)",
        header_style="bold",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Name")
    table.add_column("Address", style="cyan")
    table.add_column("", width=6)  # hint column

    for i, dev in enumerate(devices, start=1):
        name = dev.get("name") or "[dim](unknown)[/dim]"
        addr = dev.get("address") or "?"
        hint = "[bold yellow]PT-210?[/bold yellow]" if _looks_like_pt210(dev) else ""
        table.add_row(str(i), name, addr, hint)

    console.print(table)


def _prompt_choice(devices: list[dict]) -> str:
    """Ask the user which device to use. Returns the selected address."""
    from rich.console import Console
    from rich.prompt import IntPrompt

    console = Console()
    default = None
    for i, dev in enumerate(devices, start=1):
        if _looks_like_pt210(dev):
            default = i
            break

    console.print(
        "[dim]Tip: enter the number, or press Ctrl+C to abort.[/dim]"
    )
    choice = IntPrompt.ask(
        "Select device",
        choices=[str(i) for i in range(1, len(devices) + 1)],
        show_choices=False,
        default=default,
    )
    return devices[int(choice or 0) - 1]["address"]


async def _run_wizard(timeout: float) -> str:
    """End-to-end interactive flow; returns a chosen BLE address or exits."""
    from rich.console import Console

    console = Console()
    console.rule("[bold]GoojPrt PT-210 — BLE setup wizard[/bold]")
    console.print(
        "No BLE address given. [cyan]Scanning nearby devices…[/cyan]\n"
        "Make sure the printer is powered on and in range."
    )
    try:
        devices = await _scan_devices(timeout)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Scan failed:[/red] {e}")
        console.print(
            "[dim]Run with the address explicitly, e.g. "
            "[bold]goojprt-server AA:BB:CC:DD:EE:FF[/bold][/dim]"
        )
        raise SystemExit(2)

    if not devices:
        console.print("[yellow]No BLE devices found.[/yellow] Is the printer on?")
        raise SystemExit(2)

    _render_device_table(devices)
    try:
        address = _prompt_choice(devices)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Aborted.[/yellow]")
        raise SystemExit(130)

    if not (_MAC_RE.match(address) or _UUID_RE.match(address)):
        console.print(f"[red]Selected address looks invalid:[/red] {address}")
        raise SystemExit(2)

    console.print(f"[green]Selected[/green] {address}\n")
    return address


def resolve_settings(ns: argparse.Namespace) -> Settings:
    """Build :class:`Settings`, running the wizard if needed/allowed."""
    overrides = _collect_overrides(ns)
    have_address = "ble_address" in overrides or bool(os.environ.get("GOOJPRT_BLE_ADDRESS"))

    if not have_address:
        if ns.no_wizard or not _is_interactive():
            raise SystemExit(
                "ble_address is required (positional arg or GOOJPRT_BLE_ADDRESS env). "
                "Run on a terminal for the interactive scan wizard."
            )
        address = asyncio.run(_run_wizard(timeout=ns.scan_timeout))
        overrides["ble_address"] = address

    return Settings(**overrides)


def main(argv: Optional[list[str]] = None) -> None:
    import uvicorn

    from goojprt_server.app import create_app

    ns = build_parser().parse_args(argv)
    settings = resolve_settings(ns)
    app = create_app(settings=settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        lifespan="on",
        log_config=None,
    )
