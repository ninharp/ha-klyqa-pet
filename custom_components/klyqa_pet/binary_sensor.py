"""Binary sensor platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator, KlyqaDeviceData
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class KlyqaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description with an is_on extractor."""

    is_on_fn: Callable[[KlyqaDeviceData], bool]


WELLY_BINARY_SENSORS: tuple[KlyqaBinarySensorEntityDescription, ...] = (
    KlyqaBinarySensorEntityDescription(
        key="water_tray_low",
        translation_key="water_tray_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.welly.water_tray_low,
    ),
    KlyqaBinarySensorEntityDescription(
        key="pump_problem",
        translation_key="pump_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.welly.pump_status != 0,
    ),
    KlyqaBinarySensorEntityDescription(
        key="do_not_disturb",
        translation_key="do_not_disturb",
        is_on_fn=lambda data: data.welly.do_not_disturb,
    ),
    KlyqaBinarySensorEntityDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda data: data.welly.charging,
    ),
)

FOODY_BINARY_SENSORS: tuple[KlyqaBinarySensorEntityDescription, ...] = (
    KlyqaBinarySensorEntityDescription(
        key="power",
        device_class=BinarySensorDeviceClass.POWER,
        is_on_fn=lambda data: data.foody.power_state,
    ),
    KlyqaBinarySensorEntityDescription(
        key="power_adapter",
        translation_key="power_adapter",
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=lambda data: data.foody.adapter_state,
    ),
    KlyqaBinarySensorEntityDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.foody.error_state != 0,
    ),
    KlyqaBinarySensorEntityDescription(
        key="food_low",
        translation_key="food_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.foody.food_bin_state == 0,
    ),
    KlyqaBinarySensorEntityDescription(
        key="bowl_removed",
        translation_key="bowl_removed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.foody.bowl_state == 2,
    ),
)

PURIFIER_BINARY_SENSORS: tuple[KlyqaBinarySensorEntityDescription, ...] = (
    KlyqaBinarySensorEntityDescription(
        key="tilted",
        translation_key="tilted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.purifier.tilted,
    ),
    KlyqaBinarySensorEntityDescription(
        key="filter_removed",
        translation_key="filter_removed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: data.purifier.filter_removed,
    ),
    KlyqaBinarySensorEntityDescription(
        key="ionizer_active",
        translation_key="ionizer_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda data: data.purifier.ionizer_active,
    ),
)

BINARY_SENSORS_BY_TYPE: dict[DeviceType, tuple[KlyqaBinarySensorEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_BINARY_SENSORS,
    DeviceType.FOODY: FOODY_BINARY_SENSORS,
    DeviceType.AIRPURIFIER: PURIFIER_BINARY_SENSORS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaBinarySensor]:
        return [
            KlyqaBinarySensor(coordinator, description)
            for description in BINARY_SENSORS_BY_TYPE[coordinator.device_type]
        ]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaBinarySensor(KlyqaPetEntity, BinarySensorEntity):
    """A boolean condition of a Klyqa device."""

    entity_description: KlyqaBinarySensorEntityDescription

    @property
    def is_on(self) -> bool:
        """Return True if the condition holds."""
        return self.entity_description.is_on_fn(self.coordinator.data)
