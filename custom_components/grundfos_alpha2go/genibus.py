"""GENIbus protocol implementation for Grundfos Alpha2 Go over Bluetooth LE."""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError

_LOGGER = logging.getLogger(__name__)

GENI_SERVICE_UUID = "8e7f1a04-087a-44c9-b292-a2c628fdd9aa"
GENI_RX_UUID      = "8e7f1a05-087a-44c9-b292-a2c628fdd9aa"
GENI_TX_UUID      = "8e7f1a06-087a-44c9-b292-a2c628fdd9aa"

SD = 0x27
DA = 0x20
SA = 0x01

CLASS_GET      = 0x02
CLASS_MEASURED = 0x06
CLASS_EXTENDED = 0x30

ID_FLOW    = 0xA9
ID_HEAD    = 0xAA
ID_SPEED   = 0x25
ID_POWER   = 0x50
ID_VOLTAGE = 0x00
ID_CURRENT = 0x01

MEASUREMENT_IDS = [ID_FLOW, ID_HEAD, ID_SPEED, ID_POWER, ID_VOLTAGE, ID_CURRENT]


@dataclass
class PumpData:
    flow:    float | None = None
    head:    float | None = None
    speed:   int   | None = None
    power:   float | None = None
    voltage: float | None = None
    current: float | None = None


def _checksum(data: bytes) -> int:
    cs = 0
    for b in data:
        cs ^= b
    return cs


def build_get_request(info_ids: list[int]) -> bytes:
    payload = bytes([DA, SA, CLASS_GET] + info_ids)
    le = len(payload) + 1
    body = bytes([le]) + payload
    cs = _checksum(body)
    return bytes([SD]) + body + bytes([cs])


def parse_response(data: bytes) -> PumpData | None:
    if len(data) < 5:
        _LOGGER.warning("GENI response too short (%d bytes): %s", len(data), data.hex())
        return None
    if data[0] != SD:
        _LOGGER.warning("GENI bad start delimiter: 0x%02X", data[0])
        return None

    le        = data[1]
    pdu_class = data[4]

    expected_len = 1 + le + 1
    if len(data) < expected_len:
        _LOGGER.warning("GENI frame truncated (expected %d, got %d)", expected_len, len(data))
        return None

    cs_received   = data[-1]
    cs_calculated = _checksum(data[1:-1])
    if cs_received != cs_calculated:
        _LOGGER.warning("GENI checksum mismatch: 0x%02X vs 0x%02X", cs_received, cs_calculated)

    apdu = data[5:-1]

    if pdu_class == CLASS_MEASURED:
        return _decode_measured_class(apdu)
    elif pdu_class == CLASS_EXTENDED:
        return _decode_extended_class(apdu)
    else:
        _LOGGER.debug("Unknown GENI PDU class 0x%02X: %s", pdu_class, data.hex())
        return None


def _decode_measured_class(apdu: bytes) -> PumpData:
    result = PumpData()
    i = 0
    while i + 1 < len(apdu):
        info_id = apdu[i]
        value   = apdu[i + 1]
        i += 2
        if info_id == ID_FLOW:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.flow = value / 100.0
        elif info_id == ID_HEAD:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.head = value / 100.0
        elif info_id == ID_SPEED:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.speed = value
        elif info_id == ID_POWER:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.power = value / 10.0
        elif info_id == ID_VOLTAGE:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.voltage = value / 10.0
        elif info_id == ID_CURRENT:
            if i < len(apdu): value = (value << 8) | apdu[i]; i += 1
            result.current = value / 100.0
    return result


def _decode_extended_class(apdu: bytes) -> PumpData:
    result = PumpData()
    if len(apdu) < 12:
        _LOGGER.warning("Extended PDU too short (%d bytes): %s", len(apdu), apdu.hex())
    try:
        if len(apdu) >= 2:  result.flow    = struct.unpack_from(">H", apdu, 0)[0] / 100.0
        if len(apdu) >= 4:  result.head    = struct.unpack_from(">H", apdu, 2)[0] / 100.0
        if len(apdu) >= 6:  result.speed   = struct.unpack_from(">H", apdu, 4)[0]
        if len(apdu) >= 8:  result.power   = struct.unpack_from(">H", apdu, 6)[0] / 10.0
        if len(apdu) >= 10: result.voltage = struct.unpack_from(">H", apdu, 8)[0] / 10.0
        if len(apdu) >= 12: result.current = struct.unpack_from(">H", apdu, 10)[0] / 100.0
    except struct.error as exc:
        _LOGGER.error("Error decoding extended PDU: %s", exc)
    return result


class Alpha2GoClient:
    """Async BLE client for Grundfos Alpha2 Go."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None
        self._response_event = asyncio.Event()
        self._last_data: PumpData | None = None

    async def connect(self) -> None:
        _LOGGER.debug("Connecting to Alpha2 Go at %s", self._address)
        self._client = BleakClient(
            self._address,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.connect(timeout=20.0)
        await self._client.start_notify(GENI_RX_UUID, self._on_notify)
        _LOGGER.info("Connected to Alpha2 Go %s", self._address)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.warning("Alpha2 Go %s disconnected", self._address)
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def _on_notify(self, _handle: int, data: bytes) -> None:
        _LOGGER.debug("BLE notify raw: %s", data.hex())
        parsed = parse_response(data)
        if parsed is not None:
            self._last_data = parsed
            self._response_event.set()

    async def poll(self, timeout: float = 5.0) -> PumpData | None:
        if not self.is_connected:
            try:
                await self.connect()
            except Exception as exc:
                _LOGGER.error("Cannot connect to pump %s: %s", self._address, exc)
                return None

        request = build_get_request(MEASUREMENT_IDS)
        self._response_event.clear()
        try:
            await self._client.write_gatt_char(GENI_TX_UUID, request, response=True)
        except BleakError as exc:
            _LOGGER.error("BLE write failed: %s", exc)
            return None

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for GENI response from %s", self._address)
            return None

        return self._last_data
