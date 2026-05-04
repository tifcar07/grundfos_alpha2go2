"""BLE client for Grundfos Alpha2 Go - lecture Device Information."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError

_LOGGER = logging.getLogger(__name__)

# UUIDs standards Device Information (180A)
DEVICE_INFO_SERVICE  = "0000180a-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER    = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE        = "00002a26-0000-1000-8000-00805f9b34fb"

# UUID service propriétaire Alpha2 Go (pour référence future)
GENI_SERVICE_UUID    = "0000fe5d-0000-1000-8000-00805f9b34fb"
GENI_CHAR_UUID       = "859cffd1-036e-432a-aa28-1a0085b87ba9"


@dataclass
class PumpData:
    """Données lues depuis la pompe."""
    model:    str | None = None
    firmware: str | None = None
    connected: bool = False
    # Futurs capteurs (après reverse engineering protocole FE5D)
    flow:    float | None = None
    head:    float | None = None
    speed:   int   | None = None
    power:   float | None = None
    voltage: float | None = None
    current: float | None = None


class Alpha2GoClient:
    """Client BLE pour Grundfos Alpha2 Go."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None

    async def connect(self) -> None:
        _LOGGER.debug("Connexion à Alpha2 Go %s", self._address)
        self._client = BleakClient(
            self._address,
            disconnected_callback=self._on_disconnect,
        )
        await self._client.connect(timeout=20.0)
        _LOGGER.info("Connecté à Alpha2 Go %s", self._address)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.warning("Alpha2 Go %s déconnecté", self._address)
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def _read_char(self, uuid: str) -> str | None:
        """Lit une caractéristique BLE et retourne la valeur en string."""
        try:
            data = await self._client.read_gatt_char(uuid)
            return data.decode("utf-8").strip("\x00").strip()
        except Exception as exc:
            _LOGGER.debug("Impossible de lire %s: %s", uuid, exc)
            return None

    async def poll(self, timeout: float = 10.0) -> PumpData | None:
        """Connexion et lecture des informations disponibles."""
        if not self.is_connected:
            try:
                await asyncio.wait_for(self.connect(), timeout=timeout)
            except Exception as exc:
                _LOGGER.error("Cannot connect to pump %s: %s", self._address, exc)
                return None

        data = PumpData(connected=self.is_connected)

        # Lecture Device Information (service standard 180A)
        data.model    = await self._read_char(CHAR_MODEL_NUMBER)
        data.firmware = await self._read_char(CHAR_FIRMWARE)

        _LOGGER.debug(
            "Alpha2 Go %s — modèle: %s, firmware: %s",
            self._address, data.model, data.firmware
        )

        # Log des services disponibles pour future analyse protocole
        try:
            services = self._client.services
            for service in services:
                _LOGGER.info(
                    "Service BLE: %s (%s)",
                    service.uuid, service.description
                )
                for char in service.characteristics:
                    _LOGGER.info(
                        "  Caractéristique: %s | props: %s",
                        char.uuid, char.properties
                    )
        except Exception as exc:
            _LOGGER.debug("Erreur lecture services: %s", exc)

        return data
