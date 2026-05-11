"""BLE client for Grundfos Alpha2 Go v1.2.0

Discovered via BLE sniffing (nRF52840 dongle + Wireshark):
- Service: 0xFE5D (Grundfos, officially registered with Bluetooth SIG)
- Characteristic handle: 0x001A
- Characteristic UUID: 859CFFD1-036E-432A-AA28-1A0085B87BA9
- Properties: Read + Write w/o response + Notify

Note: The data exchange uses application-layer encryption (ECDH-style key
exchange + encrypted payloads). Sensor data (flow, head, power, etc.)
cannot be decoded without the proprietary protocol details.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError

_LOGGER = logging.getLogger(__name__)

# Standard Device Information service (180A)
DEVICE_INFO_SERVICE  = "0000180a-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER    = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE        = "00002a26-0000-1000-8000-00805f9b34fb"

# Generic Access service (1800)
CHAR_DEVICE_NAME     = "00002a00-0000-1000-8000-00805f9b34fb"

# Grundfos proprietary service & characteristic (discovered via sniffing)
GRUNDFOS_SERVICE_UUID = "0000fe5d-0000-1000-8000-00805f9b34fb"
GRUNDFOS_CHAR_UUID    = "859cffd1-036e-432a-aa28-1a0085b87ba9"


@dataclass
class PumpData:
    """Pump state - read from Bluetooth."""
    model:       str | None = None
    firmware:    str | None = None
    device_name: str | None = None
    connected:   bool = False
    rssi:        int | None = None
    # Notification counter - shows pump activity even without decoding
    notifications: int = 0


class Alpha2GoClient:
    """BLE client for the Grundfos Alpha2 Go pump."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None
        self._notification_count = 0

    async def connect(self) -> None:
        _LOGGER.debug("Connecting to Alpha2 Go at %s", self._address)
        self._client = BleakClient(
            self._address,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.connect(timeout=20.0)
        _LOGGER.info("Connected to Alpha2 Go %s", self._address)

        # Enable notifications on the Grundfos characteristic
        try:
            await self._client.start_notify(
                GRUNDFOS_CHAR_UUID, self._on_notify
            )
            _LOGGER.debug("Notifications enabled on Grundfos characteristic")
        except Exception as exc:
            _LOGGER.debug("Could not enable notifications: %s", exc)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.warning("Alpha2 Go %s disconnected", self._address)
        self._client = None

    def _on_notify(self, _handle: int, data: bytes) -> None:
        """Called when the pump pushes data via BLE notification."""
        self._notification_count += 1
        _LOGGER.debug(
            "BLE notify #%d from pump: %s",
            self._notification_count, data.hex()
        )

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def _read_char(self, uuid: str) -> str | None:
        try:
            data = await self._client.read_gatt_char(uuid)
            return data.decode("utf-8", errors="ignore").strip("\x00").strip()
        except Exception as exc:
            _LOGGER.debug("Cannot read %s: %s", uuid, exc)
            return None

    async def poll(self, timeout: float = 15.0) -> PumpData | None:
        """Connect and read all available information from the pump."""
        if not self.is_connected:
            try:
                await asyncio.wait_for(self.connect(), timeout=timeout)
            except Exception as exc:
                _LOGGER.error(
                    "Cannot connect to pump %s: %s", self._address, exc
                )
                return None

        data = PumpData(
            connected=self.is_connected,
            notifications=self._notification_count,
        )

        # Read identity from standard BLE services
        data.device_name = await self._read_char(CHAR_DEVICE_NAME)
        data.model       = await self._read_char(CHAR_MODEL_NUMBER)
        data.firmware    = await self._read_char(CHAR_FIRMWARE)

        _LOGGER.debug(
            "Pump %s — name: %s, model: %s, firmware: %s, notifications: %d",
            self._address, data.device_name, data.model, data.firmware,
            data.notifications
        )

        # Log all services on first poll, useful for debugging
        try:
            services = self._client.services
            for service in services:
                _LOGGER.debug("Service BLE: %s", service.uuid)
                for char in service.characteristics:
                    _LOGGER.debug(
                        "  Characteristic: %s | props: %s | handle: 0x%04X",
                        char.uuid, char.properties, char.handle
                    )
        except Exception as exc:
            _LOGGER.debug("Cannot enumerate services: %s", exc)

        return data
