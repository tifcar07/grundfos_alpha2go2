"""BLE client for Grundfos Alpha2 Go - defensive connection cleanup.

Preserves existing read-only functionality. The pump itself is not controlled.
This is a proposed patch; verify on a test system before deployment.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient

_LOGGER = logging.getLogger(__name__)

# Standard Device Information service (180A)
DEVICE_INFO_SERVICE = "0000180a-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE = "00002a26-0000-1000-8000-00805f9b34fb"

# Generic Access service (1800)
CHAR_DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"

# Grundfos proprietary service & characteristic
GRUNDFOS_SERVICE_UUID = "0000fe5d-0000-1000-8000-00805f9b34fb"
GRUNDFOS_CHAR_UUID = "859cffd1-036e-432a-aa28-1a0085b87ba9"
# Compatibility alias for config_flow.py in repository main branch.
GENI_SERVICE_UUID = GRUNDFOS_SERVICE_UUID

CONNECT_TIMEOUT = 20.0
CONNECT_GUARD_TIMEOUT = 25.0
DISCONNECT_TIMEOUT = 10.0

@dataclass
class PumpData:
    """Pump state read from Bluetooth."""

    model: str | None = None
    firmware: str | None = None
    device_name: str | None = None
    connected: bool = False
    rssi: int | None = None
    notifications: int = 0


class Alpha2GoClient:
    """Maintain one BLE connection and clean up failed sessions."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None
        self._notification_count = 0
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def _on_disconnect(self, client: BleakClient) -> None:
        # Do not overwrite self._client here. Retaining the old client lets
        # disconnect() / the next reconnect attempt clean up its resources.
        _LOGGER.warning("Alpha2 Go %s disconnected", self._address)

    def _on_notify(self, _handle: int, data: bytes) -> None:
        self._notification_count += 1
        _LOGGER.debug(
            "BLE notify #%d from pump: %s", self._notification_count, data.hex()
        )

    async def _disconnect_locked(self) -> None:
        """Dispose of the previous Bleak client, even after failed connect."""
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            # Bleak disconnect is also the documented resource-cleanup path.
            await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.warning(
                "Could not fully clean up Alpha2 Go BLE client: %s", exc
            )

    async def _connect_locked(self) -> None:
        """Start a new BLE session after cleaning up any abandoned client."""
        await self._disconnect_locked()
        client = BleakClient(self._address, disconnected_callback=self._on_disconnect)
        self._client = client
        try:
            await asyncio.wait_for(
                client.connect(timeout=CONNECT_TIMEOUT),
                timeout=CONNECT_GUARD_TIMEOUT,
            )
            _LOGGER.info("Connected to Alpha2 Go %s", self._address)
            try:
                await client.start_notify(GRUNDFOS_CHAR_UUID, self._on_notify)
            except Exception as exc:
                # Notification availability is optional for the identity reads.
                _LOGGER.debug("Could not enable notifications: %s", exc)
        except asyncio.CancelledError:
            await self._disconnect_locked()
            raise
        except Exception:
            await self._disconnect_locked()
            raise

    async def connect(self) -> None:
        """Connect explicitly; serialized with polling and unload."""
        async with self._lock:
            if not self.is_connected:
                await self._connect_locked()

    async def disconnect(self) -> None:
        """Close BLE session on unload or after a fault."""
        async with self._lock:
            await self._disconnect_locked()

    async def _read_char(self, uuid: str) -> str | None:
        client = self._client
        if client is None or not client.is_connected:
            return None
        try:
            data = await client.read_gatt_char(uuid)
            return data.decode("utf-8", errors="ignore").strip("\x00").strip()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug("Cannot read %s: %s", uuid, exc)
            return None

    async def poll(self, timeout: float = 25.0) -> PumpData | None:
        """Read pump identity. Keep the BLE connection only while healthy."""
        async with self._lock:
            if not self.is_connected:
                try:
                    # The guard is >= the Bleak connect timeout (20 seconds).
                    await asyncio.wait_for(self._connect_locked(), timeout=timeout)
                except asyncio.CancelledError:
                    await self._disconnect_locked()
                    raise
                except Exception as exc:
                    await self._disconnect_locked()
                    _LOGGER.warning(
                        "Cannot connect to Alpha2 Go %s: %s", self._address, exc
                    )
                    return None
            try:
                data = PumpData(
                    connected=self.is_connected,
                    notifications=self._notification_count,
                )
                data.device_name = await self._read_char(CHAR_DEVICE_NAME)
                data.model = await self._read_char(CHAR_MODEL_NUMBER)
                data.firmware = await self._read_char(CHAR_FIRMWARE)
                return data
            except asyncio.CancelledError:
                await self._disconnect_locked()
                raise
