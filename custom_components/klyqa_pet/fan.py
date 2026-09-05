"""Fan platform for the Klyqa air purifier."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityDescription, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .const import PURIFIER_RUN_MODES
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1

FAN_LEVELS = [1, 2, 3]
FAN_DESCRIPTION = FanEntityDescription(key="fan", translation_key="air_purifier", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fan entity for every air purifier."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaPurifierFan]:
        if coordinator.device_type is not DeviceType.AIRPURIFIER:
            return []
        return [KlyqaPurifierFan(coordinator, FAN_DESCRIPTION)]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaPurifierFan(KlyqaPetEntity, FanEntity):
    """The air purifier as a fan with three speeds and four run modes."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = len(FAN_LEVELS)
    _attr_preset_modes = list(PURIFIER_RUN_MODES.values())  # noqa: RUF012

    @property
    def is_on(self) -> bool:
        """Return True if the purifier is powered on."""
        return self.coordinator.data.purifier.power

    @property
    def percentage(self) -> int | None:
        """Return the fan level as a percentage."""
        state = self.coordinator.data.purifier
        if not state.power or state.fan_level not in FAN_LEVELS:
            return 0
        return ordered_list_item_to_percentage(FAN_LEVELS, state.fan_level)

    @property
    def preset_mode(self) -> str | None:
        """Return the run mode."""
        return PURIFIER_RUN_MODES.get(self.coordinator.data.purifier.run_mode)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Power on, then apply speed or preset if given."""
        await self._async_send(self.coordinator.purifier_device.set_power(True))
        if percentage is not None:
            await self.async_set_percentage(percentage)
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off."""
        await self._async_send(self.coordinator.purifier_device.set_power(False))

    async def async_set_percentage(self, percentage: int) -> None:
        """Map the percentage to fan level 1..3; 0 turns the purifier off."""
        if percentage == 0:
            await self.async_turn_off()
            return
        level = percentage_to_ordered_list_item(FAN_LEVELS, percentage)
        await self._async_send(self.coordinator.purifier_device.set_fan_level(level))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the run mode."""
        mode = next(key for key, name in PURIFIER_RUN_MODES.items() if name == preset_mode)
        await self._async_send(self.coordinator.purifier_device.set_run_mode(mode))
