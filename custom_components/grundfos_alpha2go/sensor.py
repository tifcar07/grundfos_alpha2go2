"""Capteurs : puissance, vitesse (+ tension/courant désactivés par défaut)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Alpha2GoCoordinator, build_device_info
from .const import CONF_ADDRESS
from .genibus import PumpData


@dataclass(frozen=True, kw_only=True)
class Alpha2GoSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PumpData], float | None]


SENSORS: tuple[Alpha2GoSensorDescription, ...] = (
    Alpha2GoSensorDescription(
        key="power",
        name="Puissance",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.power,
    ),
    Alpha2GoSensorDescription(
        key="speed",
        name="Vitesse",
        icon="mdi:rotate-right",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.speed,
    ),
    Alpha2GoSensorDescription(
        key="voltage",
        name="Tension",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.voltage,
    ),
    Alpha2GoSensorDescription(
        key="current",
        name="Courant",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.current,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Alpha2GoCoordinator = entry.runtime_data
    async_add_entities(Alpha2GoSensor(coordinator, entry, d) for d in SENSORS)


class Alpha2GoSensor(CoordinatorEntity[Alpha2GoCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: Alpha2GoSensorDescription

    def __init__(
        self,
        coordinator: Alpha2GoCoordinator,
        entry: ConfigEntry,
        description: Alpha2GoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_{description.key}"
        self._attr_device_info = build_device_info(entry)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return self.entity_description.value_fn(data) if data else None
