"""
GENIbus protocol implementation for Grundfos Alpha2 Go over Bluetooth LE.

The Alpha2 Go uses Grundfos' proprietary GENIbus protocol encapsulated in BLE GATT.
Protocol reference reverse-engineered from:
  - ESPHome Alpha3 component (jan-hofmeier)
  - openHAB Grundfos Alpha binding
  - JsBergbau/AlphaDecoder (for MI401 variant)

BLE GATT topology:
  Service  : 8e7f1a04-087a-44c9-b292-a2c628fdd9aa  (GENI Service)
  TX char  : 8e7f1a06-087a-44c9-b292-a2c628fdd9aa  (Write – send request)
  RX char  : 8e7f1a05-087a-44c9-b292-a2c628fdd9aa  (Notify – receive response)

GENIbus frame format (over BLE):
  [SD] [LE] [DA] [SA] [CLASS] [DATA...] [CS]
   SD  = Start delimiter  (0x27)
   LE  = Length of remaining bytes (excluding SD)
   DA  = Destination address (0x20 for pump)
   SA  = Source address      (0x01 for master)
   CLASS = Protocol data unit class
   CS  = Checksum (XOR of all bytes after SD, up to but not including CS)

Data class used for sensor polling:
  Class 0x02 = GET data values
  Response class 0x06 = Measured data

Known measurement IDs (ref. GENIbus spec / Alpha3 impl):
  0xA9 = Flow        (m³/h, scale 1/100)
  0xAA = Head        (m,    scale 1/100)
  0x25 = Speed       (RPM,  scale 1)
  0x50 = Power input (W,    scale 1/10)
  0x00 = Voltage     (V,    scale 1/10)
  0x50 = Current     (A,    scale 1/100)  [disambiguated by class]

NOTE for Alpha2 Go:
  Firmware variants may return "Type 48" (0x30) responses, which appear
  to be an extended/proprietary PDU. This implementation attempts to
  decode both standard Alpha3 responses and the extended type.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError

_LOGGER = logging.getLogger(__name__)

# ── BLE UUIDs ──────────────────────────────────────────────────────────────────
GENI_SERVICE_UUID = "8e7f1a04-087a-44c9-b292-a2c628fdd9aa"
GENI_RX_UUID      = "8e7f1a05-087a-44c9-b292-a2c628fdd9aa"  # pump → HA (notify)
GENI_TX_UUID      = "8e7f1a06-087a-44c9-b292-a2c628fdd9aa"  # HA → pump (write)

# ── GENIbus frame constants ────────────────────────────────────────────────────
SD   = 0x27   # Start delimiter
DA   = 0x20   # Destination: pump
SA   = 0x01   # Source: master (us)

# PDU classes
CLASS_GET          = 0x02
CLASS_MEASURED     = 0x06
CLASS_EXTENDED     = 0x30   # Seen on Alpha2 Go / newer Alpha3 firmware

# Measurement info-codes (APDU IDs)
ID_FLOW    = 0xA9
ID_HEAD    = 0xAA
ID_SPEED   = 0x25
ID_POWER   = 0x50
ID_VOLTAGE = 0x00
ID_CURRENT = 0x01

# Full "get all measurements" request payload
MEASUREMENT_IDS = [ID_FLOW, ID_HEAD, ID_SPEED, ID_POWER, ID_VOLTAGE, ID_CURRENT]


@dataclass
class PumpData:
    """Decoded sensor values from the pump."""
    flow:    float | None = None   # m³/h
    head:    float | None = None   # m
    speed:   int   | None = None   # RPM
    power:   float | None = None   # W
    voltage: float | None = None   # V
    current: float | None = None   # A


# ── Frame helpers ──────────────────────────────────────────────────────────────

def _checksum(data: bytes) -> int:
    """XOR checksum over all bytes."""
    cs = 0
    for b in data:
        cs ^= b
    return cs


def build_get_request(info_ids: list[int]) -> bytes:
    """
    Build a GENIbus GET request frame.

    Frame:  SD  LE  DA  SA  CL  [IDs...]  CS
    """
    payload = bytes([DA, SA, CLASS_GET] + info_ids)
    le = len(payload) + 1          # +1 for CS byte itself
    body = bytes([le]) + payload
    cs = _checksum(body)
    return bytes([SD]) + body + bytes([cs])


def parse_response(data: bytes) -> PumpData | None:
    """
    Parse a GENIbus response frame into a PumpData object.

    Returns None if the frame is invalid or unrecognised.
    """
    if len(data) < 5:
        _LOGGER.warning("GENI response too short (%d bytes): %s", len(data), data.hex())
        return None

    if data[0] != SD:
        _LOGGER.warning("GENI bad start delimiter: 0x%02X", data[0])
        return None

    le       = data[1]
    da       = data[2]   # noqa: F841  (unused but logged for debug)
    sa       = data[3]   # noqa: F841
    pdu_class = data[4]

    expected_len = 1 + le + 1  # SD + body + CS
    if len(data) < expected_len:
        _LOGGER.warning("GENI frame truncated (expected %d, got %d)", expected_len, len(data))
        return None

    # Verify checksum
    cs_received = data[-1]
    cs_calculated = _checksum(data[1:-1])
    if cs_received != cs_calculated:
        _LOGGER.warning(
            "GENI checksum mismatch: received 0x%02X, calculated 0x%02X",
            cs_received, cs_calculated
        )
        # Continue anyway — some firmware versions have off-by-one behaviour

    apdu = data[5:-1]   # Application PDU bytes between header and CS

    if pdu_class == CLASS_MEASURED:
        return _decode_measured_class(apdu)
    elif pdu_class == CLASS_EXTENDED:
        return _decode_extended_class(apdu)
    else:
        _LOGGER.debug(
            "Unknown GENI PDU class 0x%02X, raw: %s",
            pdu_class, " ".join(f"{b:02X}" for b in data)
        )
        return None


def _decode_measured_class(apdu: bytes) -> PumpData:
    """Decode standard class-0x06 measured-data APDU."""
    result = PumpData()
    i = 0
    while i + 1 < len(apdu):
        info_id = apdu[i]
        value   = apdu[i + 1]
        i += 2

        if info_id == ID_FLOW:
            # 16-bit value when high byte follows
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.flow = value / 100.0

        elif info_id == ID_HEAD:
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.head = value / 100.0

        elif info_id == ID_SPEED:
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.speed = value

        elif info_id == ID_POWER:
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.power = value / 10.0

        elif info_id == ID_VOLTAGE:
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.voltage = value / 10.0

        elif info_id == ID_CURRENT:
            if i < len(apdu):
                value = (value << 8) | apdu[i]
                i += 1
            result.current = value / 100.0

    return result


def _decode_extended_class(apdu: bytes) -> PumpData:
    """
    Decode extended PDU class 0x30, observed on Alpha2 Go and newer Alpha3.

    The layout appears to be fixed-width 16-bit big-endian fields:
      [0:2]  = Flow    (1/100 m³/h)
      [2:4]  = Head    (1/100 m)
      [4:6]  = Speed   (RPM)
      [6:8]  = Power   (1/10 W)
      [8:10] = Voltage (1/10 V)
      [10:12]= Current (1/100 A)

    This layout is inferred from field observations and may need adjustment.
    Enable DEBUG logging to inspect raw bytes if values look wrong.
    """
    result = PumpData()

    if len(apdu) < 12:
        _LOGGER.warning(
            "Extended PDU too short for full decode (%d bytes): %s",
            len(apdu), apdu.hex()
        )

    try:
        if len(apdu) >= 2:
            result.flow    = struct.unpack_from(">H", apdu, 0)[0] / 100.0
        if len(apdu) >= 4:
            result.head    = struct.unpack_from(">H", apdu, 2)[0] / 100.0
        if len(apdu) >= 6:
            result.speed   = struct.unpack_from(">H", apdu, 4)[0]
        if len(apdu) >= 8:
            result.power   = struct.unpack_from(">H", apdu, 6)[0] / 10.0
        if len(apdu) >= 10:
            result.voltage = struct.unpack_from(">H", apdu, 8)[0] / 10.0
        if len(apdu) >= 12:
            result.current = struct.unpack_from(">H", apdu, 10)[0] / 100.0
    except struct.error as exc:
        _LOGGER.error("Error decoding extended PDU: %s", exc)

    return result


# ── BLE client ─────────────────────────────────────────────────────────────────

class Alpha2GoClient:
    """Async BLE client for the Grundfos Alpha2 Go pump."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None
        self._response_event = asyncio.Event()
        self._last_data: PumpData | None = None

    # ── connection ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the pump and enable BLE notifications."""
        _LOGGER.debug("Connecting to Alpha2 Go at %s", self._address)
        self._client = BleakClient(self._address, disconnected_callback=self._on_disconnect)
        await self._client.connect(timeout=15.0)
        await self._client.start_notify(GENI_RX_UUID, self._on_notify)
        _LOGGER.info("Connected to Alpha2 Go %s", self._address)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    def _on_disconnect(self, client: BleakClient) -> None:  # noqa: ARG002
        _LOGGER.warning("Alpha2 Go %s disconnected", self._address)
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ── notification handler ───────────────────────────────────────────────────

    def _on_notify(self, _handle: int, data: bytes) -> None:
        _LOGGER.debug("BLE notify raw: %s", data.hex())
        parsed = parse_response(data)
        if parsed is not None:
            self._last_data = parsed
            self._response_event.set()

    # ── polling ────────────────────────────────────────────────────────────────

    async def poll(self, timeout: float = 5.0) -> PumpData | None:
        """
        Send a GENIbus GET request and wait for the pump's response.

        The pump can only hold one BLE connection at a time.
        Reconnects automatically if the link was lost.
        """
        if not self.is_connected:
            try:
                await self.connect()
            except BleakError as exc:
                _LOGGER.error("Cannot connect to pump %s: %s", self._address, exc)
                return None

        request = build_get_request(MEASUREMENT_IDS)
        _LOGGER.debug("Sending GENI request: %s", request.hex())

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
