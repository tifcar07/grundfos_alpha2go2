"""Client GENIbus over BLE pour Grundfos Alpha2 Go (lecture seule).

Principe : une connexion COURTE par lecture.
  connexion -> abonnement notifications -> requête GENIbus "power"
  -> attente réponse -> désabonnement -> déconnexion (toujours, via finally).

Trames reprises du composant ESPHome `alpha3` (même service BLE FE5D /
caractéristique 859cffd1-...). Compatibilité Alpha2 Go à valider : en cas de
réponse inconnue, la trame brute est journalisée en DEBUG.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import struct
from dataclasses import dataclass

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)

from .const import RUNNING_POWER_THRESHOLD_W, RUNNING_SPEED_THRESHOLD_RPM

_LOGGER = logging.getLogger(__name__)

GENI_SERVICE_UUID = "0000fe5d-0000-1000-8000-00805f9b34fb"
GENI_CHAR_UUID = "859cffd1-036e-432a-aa28-1a0085b87ba9"

# Requête "power" (ESPHome alpha3) : tension, courant, puissance, vitesse
REQUEST_POWER = bytes([0x27, 0x07, 0xE7, 0xF8, 0x0A, 0x03, 0x57, 0x00, 0x45, 0x8A, 0xCD])

RESPONSE_START = 0x24
RESPONSE_HEADER_LENGTH = 13
RESPONSE_TYPE_POWER = bytes([44, 0, 1, 0, 1, 0, 0, 37])
OFFSET_VOLTAGE_AC = 0
OFFSET_CURRENT = 8
OFFSET_POWER = 12
OFFSET_SPEED = 20
# Octets nécessaires pour lire jusqu'à la vitesse incluse
MIN_POWER_FRAME = RESPONSE_HEADER_LENGTH + OFFSET_SPEED + 4

RESPONSE_TIMEOUT = 5.0
DISCONNECT_TIMEOUT = 10.0
OVERALL_TIMEOUT = 60.0


class GenibusError(Exception):
    """Lecture GENIbus impossible."""


@dataclass
class PumpData:
    """Valeurs lues sur la pompe."""

    power: float | None = None  # W
    speed: float | None = None  # tr/min
    voltage: float | None = None  # V
    current: float | None = None  # A

    @property
    def running(self) -> bool | None:
        if self.power is None and self.speed is None:
            return None
        return (self.power or 0.0) >= RUNNING_POWER_THRESHOLD_W or (
            self.speed or 0.0
        ) >= RUNNING_SPEED_THRESHOLD_RPM


class Alpha2GoClient:
    """Une lecture = une connexion courte, toujours refermée."""

    def __init__(self, address: str) -> None:
        self.address = address.upper()
        self._lock = asyncio.Lock()
        self._expected_disconnect = False

    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        if self._expected_disconnect:
            _LOGGER.debug("Alpha2 Go %s : déconnexion normale", self.address)
        else:
            _LOGGER.debug(
                "Alpha2 Go %s : connexion coupée par la pompe pendant la lecture",
                self.address,
            )

    async def async_read(self, ble_device: BLEDevice) -> PumpData:
        """Lire puissance/vitesse. Lève GenibusError en cas d'échec."""
        async with self._lock:
            try:
                async with asyncio.timeout(OVERALL_TIMEOUT):
                    return await self._read_locked(ble_device)
            except TimeoutError as err:
                raise GenibusError("délai global dépassé") from err
            except BleakNotFoundError as err:
                raise GenibusError("pompe introuvable (hors de portée ?)") from err
            except BleakError as err:
                raise GenibusError(f"erreur BLE : {err}") from err

    async def _read_locked(self, ble_device: BLEDevice) -> PumpData:
        buffer = bytearray()
        complete = asyncio.Event()

        def _on_notify(_char: object, data: bytearray) -> None:
            if not buffer and (len(data) < 5 or data[0] != RESPONSE_START):
                _LOGGER.debug("Notification ignorée : %s", bytes(data).hex())
                return
            buffer.extend(data)
            if len(buffer) >= MIN_POWER_FRAME:
                complete.set()

        client = await self._connect(ble_device)
        try:
            await client.start_notify(GENI_CHAR_UUID, _on_notify)
            await client.write_gatt_char(GENI_CHAR_UUID, REQUEST_POWER, response=False)
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    await complete.wait()
            except TimeoutError:
                _LOGGER.debug(
                    "Réponse incomplète (%d octets) : %s", len(buffer), buffer.hex()
                )
        finally:
            self._expected_disconnect = True
            if client.is_connected:
                with contextlib.suppress(BleakError, TimeoutError):
                    await client.stop_notify(GENI_CHAR_UUID)
            await self._safe_disconnect(client)

        if not buffer:
            raise GenibusError(
                "aucune réponse de la pompe — appairage probablement nécessaire "
                "(bouton « Appairer » de l'appareil)"
            )
        return self._parse(bytes(buffer))

    async def _connect(self, ble_device: BLEDevice) -> BleakClientWithServiceCache:
        self._expected_disconnect = False
        return await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            f"Alpha2 Go {self.address}",
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
        )

    async def _safe_disconnect(self, client: BleakClientWithServiceCache) -> None:
        self._expected_disconnect = True
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await client.disconnect()
        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("Déconnexion incomplète : %s", err)

    async def async_pair(self, ble_device: BLEDevice) -> None:
        """Appairage (bonding) BLE. Le bouton de connectivité de la pompe doit être actif."""
        async with self._lock:
            try:
                async with asyncio.timeout(OVERALL_TIMEOUT):
                    client = await self._connect(ble_device)
                    try:
                        await client.pair()
                    finally:
                        await self._safe_disconnect(client)
            except NotImplementedError as err:
                raise GenibusError(
                    "appairage non supporté par cet adaptateur / proxy Bluetooth"
                ) from err
            except TimeoutError as err:
                raise GenibusError("délai dépassé pendant l'appairage") from err
            except BleakError as err:
                raise GenibusError(f"erreur BLE : {err}") from err
        _LOGGER.info("Alpha2 Go %s : appairage réussi", self.address)

    @staticmethod
    def _parse(frame: bytes) -> PumpData:
        if len(frame) < RESPONSE_HEADER_LENGTH:
            raise GenibusError(
                f"réponse trop courte ({len(frame)} octets) : {frame.hex() or 'vide'}"
            )
        if frame[0] != RESPONSE_START or frame[2] != 0xF8 or frame[3] != 0xE7:
            raise GenibusError(f"en-tête inattendu : {frame[:5].hex()}")
        response_type = frame[5:RESPONSE_HEADER_LENGTH]
        if response_type != RESPONSE_TYPE_POWER:
            raise GenibusError(
                f"type de réponse non reconnu {list(response_type)} — trame : {frame.hex()}"
            )
        _LOGGER.debug("Trame power : %s", frame.hex())

        def _float(offset: int) -> float | None:
            start = RESPONSE_HEADER_LENGTH + offset
            if len(frame) < start + 4:
                return None
            value = struct.unpack(">f", frame[start : start + 4])[0]
            if math.isnan(value) or math.isinf(value) or abs(value) > 1e6:
                return None
            return round(value, 2)

        return PumpData(
            voltage=_float(OFFSET_VOLTAGE_AC),
            current=_float(OFFSET_CURRENT),
            power=_float(OFFSET_POWER),
            speed=_float(OFFSET_SPEED),
        )
