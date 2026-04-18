"""Duck-typed stand-in for :class:`goojprt.GoojPrtPT210`.

Records every call in ``self.calls`` as a list of ``(method, kwargs)``
tuples. ``fail_n_times`` makes the first N BLE writes raise
``BleakError`` so the worker's reconnect path can be exercised.
"""

from __future__ import annotations

from bleak.exc import BleakError


class FakePrinter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_n_times: int = 0
        self._failures_used = 0
        self._connected = False
        self._on_disconnect_cb = None

    @property
    def is_connected_ble(self) -> bool:
        return self._connected

    async def connect_ble(self, address: str, *, on_disconnect=None) -> None:
        self._maybe_fail("connect_ble", {"address": address})
        self.calls.append(("connect_ble", {"address": address}))
        self._on_disconnect_cb = on_disconnect
        self._connected = True

    async def disconnect(self) -> None:
        self.calls.append(("disconnect", {}))
        self._connected = False

    async def initialize(self) -> None:
        self.calls.append(("initialize", {}))

    def _maybe_fail(self, method: str, kwargs: dict) -> None:
        if self._failures_used < self.fail_n_times:
            self._failures_used += 1
            self._connected = False
            self.calls.append((f"{method}:FAIL", kwargs))
            raise BleakError(f"simulated BLE failure ({self._failures_used})")

    async def print_text(self, **kwargs) -> None:
        self._maybe_fail("print_text", kwargs)
        self.calls.append(("print_text", kwargs))

    async def print_text_image(self, **kwargs) -> None:
        self._maybe_fail("print_text_image", kwargs)
        self.calls.append(("print_text_image", kwargs))

    async def print_qr(self, **kwargs) -> None:
        self._maybe_fail("print_qr", kwargs)
        self.calls.append(("print_qr", kwargs))

    async def print_pdf417(self, **kwargs) -> None:
        self._maybe_fail("print_pdf417", kwargs)
        self.calls.append(("print_pdf417", kwargs))

    async def print_image(self, image) -> None:
        self._maybe_fail("print_image", {"image": image})
        self.calls.append(("print_image", {"image": image}))

    async def feed(self, lines: int = 3) -> None:
        self._maybe_fail("feed", {"lines": lines})
        self.calls.append(("feed", {"lines": lines}))

    async def query_full_info(self, timeout: float = 1.5) -> dict:
        self.calls.append(("query_full_info", {"timeout": timeout}))
        return {
            "ble_battery": {"level_pct": 87},
            "escpos_status": {"paper": {"ok": True}},
        }
