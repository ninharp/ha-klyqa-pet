"""Select platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .const import (
    FOODY_BATTERY_MODE,
    FOODY_CHARGING_PROTECTION,
    FOODY_CUSTOM_BUTTON,
    WELLY_MODES,
)
from .coordinator import KlyqaDeviceCoordinator, KlyqaDeviceData
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KlyqaSelectEntityDescription(SelectEntityDescription):
    """Select description mapping device integers to option keys."""

    options_map: dict[int, str]
    current_fn: Callable[[KlyqaDeviceData], int]
    set_fn: Callable[[KlyqaDeviceCoordinator, int], Coroutine[Any, Any, Any]]


def _foody_setting(key: str, options_map: dict[int, str]) -> KlyqaSelectEntityDescription:
    return KlyqaSelectEntityDescription(
        key=key,
        translation_key=key,
        options=list(options_map.values()),
        options_map=options_map,
        entity_category=EntityCategory.CONFIG,
        current_fn=lambda data: int(getattr(data.foody_settings, key)),
        set_fn=lambda coordinator, value: coordinator.foody_device.update_settings(**{key: value}),
    )


WELLY_SELECTS: tuple[KlyqaSelectEntityDescription, ...] = (
    KlyqaSelectEntityDescription(
        key="mode",
        translation_key="mode",
        options=list(WELLY_MODES.values()),
        options_map=WELLY_MODES,
        current_fn=lambda data: data.welly.mode,
        set_fn=lambda coordinator, value: coordinator.welly_device.set_mode(value),
    ),
)

FOODY_SELECTS: tuple[KlyqaSelectEntityDescription, ...] = (
    _foody_setting("custom_button_function", FOODY_CUSTOM_BUTTON),
    _foody_setting("battery_work_mode", FOODY_BATTERY_MODE),
    _foody_setting("charging_protection", FOODY_CHARGING_PROTECTION),
)

SELECTS_BY_TYPE: dict[DeviceType, tuple[KlyqaSelectEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_SELECTS,
    DeviceType.FOODY: FOODY_SELECTS,
    DeviceType.AIRPURIFIER: (),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaSelect]:
        return [
            KlyqaSelect(coordinator, description)
            for description in SELECTS_BY_TYPE[coordinator.device_type]
        ]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaSelect(KlyqaPetEntity, SelectEntity):
    """An enumerated setting of a Klyqa device."""

    entity_description: KlyqaSelectEntityDescription

    @property
    def current_option(self) -> str | None:
        """Return the option key for the device value."""
        return self.entity_description.options_map.get(
            self.entity_description.current_fn(self.coordinator.data)
        )

    async def async_select_option(self, option: str) -> None:
        """Send the device value for the chosen option."""
        value = next(
            key for key, name in self.entity_description.options_map.items() if name == option
        )
        await self._async_send(self.entity_description.set_fn(self.coordinator, value))
