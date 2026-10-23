"""Characteristic selection on the GATT layout of a real PT-210, and its GS I identity answers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from goojprt.constants import (
    BLE_NOTIFY_CHAR_UUID,
    BLE_NOTIFY_CHAR_UUID_ALT,
    BLE_SERVICE_UUID,
    BLE_SERVICE_UUID_ALT,
    BLE_WRITE_CHAR_UUID,
    BLE_WRITE_CHAR_UUID_ALT,
)
from goojprt.printer import GoojPrtPT210, _identity_text
from goojprt.transport.ble import BleTransport

NOTIFY, WRITE_NW = ["notify"], ["write", "write-without-response"]


def _char(uuid, props, max_size=237):
    char = MagicMock()
    char.uuid = uuid
    char.properties = props
    char.max_write_without_response_size = max_size
    return char


def _service(uuid, *chars):
    service = MagicMock()
    service.uuid = uuid
    service.characteristics = list(chars)
    return service


#: Services in the order CoreBluetooth listed them for a PT-210 (firmware PT-210-8008).
def _real_pt210():
    return [
        _service("000018f0-0000-1000-8000-00805f9b34fb",
                 _char("00002af0-0000-1000-8000-00805f9b34fb", NOTIFY),
                 _char("00002af1-0000-1000-8000-00805f9b34fb", WRITE_NW),
                 _char("0000ff03-0000-1000-8000-00805f9b34fb", NOTIFY)),
        _service("0000fee7-0000-1000-8000-00805f9b34fb",
                 _char("0000fec8-0000-1000-8000-00805f9b34fb", ["indicate"]),
                 _char("0000fec7-0000-1000-8000-00805f9b34fb", WRITE_NW)),
        _service(BLE_SERVICE_UUID_ALT,
                 _char(BLE_NOTIFY_CHAR_UUID_ALT, NOTIFY),
                 _char(BLE_WRITE_CHAR_UUID_ALT, WRITE_NW),
                 _char("0000ff03-0000-1000-8000-00805f9b34fb", NOTIFY)),
        _service("e7810a71-73ae-499d-8c15-faa9aef0c3f2",
                 _char("bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
                       ["indicate", "write", "read", "write-without-response", "notify"])),
        _service(BLE_SERVICE_UUID,
                 _char(BLE_NOTIFY_CHAR_UUID, NOTIFY),
                 _char(BLE_WRITE_CHAR_UUID, WRITE_NW),
                 _char("49535343-aca3-481c-91ec-d85e28a60318", ["write", "notify"])),
    ]


async def _connect(services):
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.start_notify = AsyncMock()
    client.services = services
    transport = BleTransport()
    with patch("goojprt.transport.ble.BLEAK_AVAILABLE", True), \
         patch("goojprt.transport.ble.BleakClient", return_value=client):
        await transport.connect("AA:BB")
    return transport, client


@pytest.mark.asyncio
async def test_real_pt210_uses_the_primary_write_and_its_own_notify_characteristic():
    transport, client = await _connect(_real_pt210())
    assert transport._write_char == BLE_WRITE_CHAR_UUID
    assert transport._notify_char == BLE_NOTIFY_CHAR_UUID      # not 0000ff01, which comes first
    client.start_notify.assert_awaited_once()
    assert client.start_notify.await_args.args[0] == BLE_NOTIFY_CHAR_UUID


@pytest.mark.asyncio
async def test_the_service_order_does_not_matter():
    services = _real_pt210()
    for ordering in (services, list(reversed(services)), services[2:] + services[:2]):
        transport, _ = await _connect(list(ordering))
        assert (transport._write_char, transport._notify_char) == (BLE_WRITE_CHAR_UUID, BLE_NOTIFY_CHAR_UUID)


@pytest.mark.asyncio
async def test_alternate_family_alone_is_still_paired():
    alt_only = [s for s in _real_pt210() if s.uuid == BLE_SERVICE_UUID_ALT]
    transport, _ = await _connect(alt_only)
    assert (transport._write_char, transport._notify_char) == (BLE_WRITE_CHAR_UUID_ALT, BLE_NOTIFY_CHAR_UUID_ALT)


@pytest.mark.asyncio
async def test_notify_falls_back_to_another_service_when_the_write_service_has_none():
    services = [
        _service(BLE_SERVICE_UUID, _char(BLE_WRITE_CHAR_UUID, WRITE_NW)),
        _service(BLE_SERVICE_UUID_ALT, _char(BLE_NOTIFY_CHAR_UUID_ALT, NOTIFY)),
    ]
    transport, _ = await _connect(services)
    assert transport._write_char == BLE_WRITE_CHAR_UUID
    assert transport._notify_char == BLE_NOTIFY_CHAR_UUID_ALT


@pytest.mark.asyncio
async def test_a_primary_notify_is_preferred_in_the_fallback():
    services = [
        _service(BLE_SERVICE_UUID, _char(BLE_WRITE_CHAR_UUID, WRITE_NW)),
        _service(BLE_SERVICE_UUID_ALT, _char(BLE_NOTIFY_CHAR_UUID_ALT, NOTIFY)),
        _service("other", _char(BLE_NOTIFY_CHAR_UUID, NOTIFY)),
    ]
    transport, _ = await _connect(services)
    assert transport._notify_char == BLE_NOTIFY_CHAR_UUID


@pytest.mark.asyncio
async def test_a_device_without_any_known_notify_characteristic_has_none():
    services = [_service(BLE_SERVICE_UUID, _char(BLE_WRITE_CHAR_UUID, WRITE_NW))]
    transport, client = await _connect(services)
    assert transport.has_notify is False
    client.start_notify.assert_not_called()


@pytest.mark.asyncio
async def test_the_payload_limit_comes_from_the_chosen_write_characteristic():
    services = _real_pt210()
    services[-1].characteristics[1].max_write_without_response_size = 100     # primary write
    transport, _ = await _connect(services)
    assert transport._max_payload == 100


# ── GS I identity answers ────────────────────────────────────────────────────

@pytest.mark.parametrize("answer, text", [
    (b"PT-210-8008", "PT-210-8008"),          # no marker
    (b"-GEZHI", "GEZHI"),                     # markers seen on a PT-210
    (b"-PT2D-V1.0", "PT2D-V1.0"),
    (b"_17030800001", "17030800001"),         # Epson's marker
    (b"_Model\x00", "Model"),                 # NUL terminated
    (b"", ""), (b"\x00\x00", ""), (b"-", ""), (b"\x01\x02", ""),
])
def test_identity_text(answer, text):
    assert _identity_text(answer) == text


class _AnsweringTransport:
    """Fake transport that answers each GS I request from a table."""

    has_notify = True

    def __init__(self, answers):
        self.answers, self.last = answers, b""

    def clear_notify_buffer(self):
        pass

    async def write(self, data):
        self.last = bytes(data)

    async def read_notify(self, timeout):
        return self.answers.get(self.last, b"")


@pytest.mark.asyncio
async def test_query_printer_info_reports_the_text_identity_of_the_unit():
    answers = {
        b"\x1d\x49\x01": b"`", b"\x1d\x49\x02": b"\x03", b"\x1d\x49\x03": b"\x08",
        b"\x1d\x49\x41": b"PT-210-8008", b"\x1d\x49\x42": b"-GEZHI",
        b"\x1d\x49\x43": b"-PT2D-V1.0", b"\x1d\x49\x44": b"_17030800001",
    }
    printer = GoojPrtPT210()
    printer._ble = _AnsweringTransport(answers)
    info = await printer.query_printer_info(timeout=0.7)
    assert info["firmware_version"] == "PT-210-8008"
    assert info["manufacturer"] == "GEZHI"
    assert info["model_name"] == "PT2D-V1.0"
    assert info["serial_number"] == "17030800001"
    assert info["raw_responses"] == [[0x60], [0x08], [0x03]]


@pytest.mark.asyncio
async def test_unanswered_identity_queries_are_left_out():
    printer = GoojPrtPT210()
    printer._ble = _AnsweringTransport({b"\x1d\x49\x41": b"FW-1"})
    info = await printer.query_printer_info(timeout=0.7)
    assert info["firmware_version"] == "FW-1"
    for key in ("manufacturer", "model_name", "serial_number"):
        assert key not in info


@pytest.mark.asyncio
async def test_the_time_budget_is_shared_by_all_eleven_queries():
    waits = []

    class Transport(_AnsweringTransport):
        async def read_notify(self, timeout):
            waits.append(timeout)
            return b""

    printer = GoojPrtPT210()
    printer._ble = Transport({})
    await printer.query_printer_info(timeout=1.1)
    assert len(waits) == 7 and all(w == pytest.approx(0.1571, abs=1e-3) for w in waits)
