"""Number platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KlyqaNumberEntityDescription(NumberEntityDescription):
    """Number description with value extractor and command."""

    value_fn: Callable[[KlyqaDeviceCoordinator], float | None]
    set_fn: Callable[[KlyqaDeviceCoordinator, int], Coroutine[Any, Any, Any]]
    local_only: bool = False


async def _set_portions(coordinator: KlyqaDeviceCoordinator, value: int) -> None:
    coordinator.dispense_portions = value


WELLY_NUMBERS: tuple[KlyqaNumberEntityDescription, ...] = (
    KlyqaNumberEntityDescription(
        key="heating_temperature",
        translation_key="heating_temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=20,
        native_max_value=40,
        native_step=1,
        value_fn=lambda c: c.data.welly.heating_temperature,
        set_fn=lambda c, value: c.welly_device.set_heating(True, value),
    ),
    KlyqaNumberEntityDescription(
        key="daily_drinking_goal",
        translation_key="daily_drinking_goal",
        device_class=NumberDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        native_min_value=50,
        native_max_value=3000,
        native_step=50,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.welly.daily_goal,
        set_fn=lambda c, value: c.welly_device.set_daily_goal(value),
    ),
    KlyqaNumberEntityDescription(
        key="radar_sensitivity",
        translation_key="radar_sensitivity",
        native_min_value=0,
        native_max_value=2,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.welly_settings.radar_sensitivity,
        set_fn=lambda c, value: c.welly_device.update_settings(radar_sensitivity=value),
    ),
    KlyqaNumberEntityDescription(
        key="circulation_pump_speed",
        translation_key="circulation_pump_speed",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.welly_settings.circulation_pump_speed,
        set_fn=lambda c, value: c.welly_device.update_settings(circulation_pump_speed=value),
    ),
    KlyqaNumberEntityDescription(
        key="threshold_clean_tank_low",
        translation_key="threshold_clean_tank_low",
        device_class=NumberDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        native_min_value=0,
        native_max_value=3600,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.welly_settings.threshold_clean_tank_low,
        set_fn=lambda c, value: c.welly_device.update_settings(threshold_clean_tank_low=value),
    ),
    KlyqaNumberEntityDescription(
        key="threshold_dirty_tank_full",
        translation_key="threshold_dirty_tank_full",
        device_class=NumberDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        native_min_value=0,
        native_max_value=3600,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.welly_settings.threshold_dirty_tank_full,
        set_fn=lambda c, value: c.welly_device.update_settings(threshold_dirty_tank_full=value),
    ),
)

FOODY_NUMBERS: tuple[KlyqaNumberEntityDescription, ...] = (
    KlyqaNumberEntityDescription(
        key="portions",
        translation_key="portions",
        native_min_value=1,
        native_max_value=40,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.dispense_portions,
        set_fn=_set_portions,
        local_only=True,
    ),
    KlyqaNumberEntityDescription(
        key="feed_audio_volume",
        translation_key="feed_audio_volume",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.foody_settings.feed_audio_volume,
        set_fn=lambda c, value: c.foody_device.update_settings(feed_audio_volume=value),
    ),
)

NUMBERS_BY_TYPE: dict[DeviceType, tuple[KlyqaNumberEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_NUMBERS,
    DeviceType.FOODY: FOODY_NUMBERS,
    DeviceType.AIRPURIFIER: (),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up numbers for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaNumber]:
        return [
            KlyqaNumber(coordinator, description)
            for description in NUMBERS_BY_TYPE[coordinator.device_type]
        ]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaNumber(KlyqaPetEntity, NumberEntity):
    """A numeric setting of a Klyqa device."""

    entity_description: KlyqaNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the device (or keep it locally for helper numbers)."""
        if self.entity_description.local_only:
            await self.entity_description.set_fn(self.coordinator, int(value))
            self.async_write_ha_state()
            return
        await self._async_send(self.entity_description.set_fn(self.coordinator, int(value)))
