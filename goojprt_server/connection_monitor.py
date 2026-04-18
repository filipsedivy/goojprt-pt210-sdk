"""Reconnection state machine for the BLE link.

``ConnectionMonitor`` is the single source of truth for reconnect state.
``run_monitor`` is the background task that drives the reconnect loop.
Both the worker (on BleakError) and the bleak disconnected_callback call
``monitor.signal_disconnect()`` to start a reconnect cycle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from goojprt_server.logging_setup import glyph

if TYPE_CHECKING:
    from goojprt_server.config import Settings

ble_log = logging.getLogger("goojprt_server.ble")


@dataclass
class ConnectionMonitor:
    is_reconnecting: bool = False
    attempt: int = 0
    reconnected: asyncio.Event = field(default_factory=asyncio.Event)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    def signal_disconnect(self) -> None:
        """Mark as reconnecting and wake the monitor task.

        Idempotent — safe to call multiple times while a reconnect is
        already in progress.
        """
        if not self.is_reconnecting:
            self.is_reconnecting = True
        self.reconnected.clear()  # always clear — handles double-disconnect
        self._wake.set()


async def run_monitor(
    monitor: ConnectionMonitor,
    printer,
    settings: "Settings",
    *,
    on_disconnect=None,
) -> None:
    """Wait for a disconnect signal then drive the reconnect loop forever."""
    while True:
        try:
            await monitor._wake.wait()
            monitor._wake.clear()

            if not monitor.is_reconnecting:
                continue

            ble_log.warning("%s BLE disconnected — starting reconnect loop", glyph("dots"))
            reconnect_started_at = time.monotonic()
            last_logged_at = reconnect_started_at

            while True:
                monitor.attempt += 1
                elapsed = time.monotonic() - reconnect_started_at
                if monitor.attempt > 1:
                    since_log = time.monotonic() - last_logged_at
                    if since_log >= settings.reconnect_log_interval_s:
                        ble_log.warning(
                            "%s still reconnecting… (attempt %d, %.0fs elapsed)",
                            glyph("dots"), monitor.attempt, elapsed,
                        )
                        last_logged_at = time.monotonic()

                try:
                    await printer.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await printer.connect_ble(settings.ble_address, on_disconnect=on_disconnect)
                    await printer.initialize()
                    ble_log.info(
                        "%s reconnected after %d attempt(s) (%.1fs)",
                        glyph("ok"), monitor.attempt, time.monotonic() - reconnect_started_at,
                    )
                    monitor.is_reconnecting = False
                    monitor.attempt = 0
                    monitor.reconnected.set()
                    break
                except Exception as e:  # noqa: BLE001
                    ble_log.error(
                        "%s reconnect attempt %d failed: %s",
                        glyph("err"), monitor.attempt, e,
                    )
                    await asyncio.sleep(settings.reconnect_interval_s)

        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            ble_log.exception("monitor loop crashed; restarting")
