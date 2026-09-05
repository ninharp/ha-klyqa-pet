"""Light platform for the Klyqa air purifier LED ring."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_RGB_COLOR,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1

LED_DESCRIPTION = LightEntityDescription(key="led", translation_key="led")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LED light for every air purifier."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaPurifierLight]:
        if coordinator.device_type is not DeviceType.AIRPURIFIER:
            return []
        return [KlyqaPurifierLight(coordinator, LED_DESCRIPTION)]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaPurifierLight(KlyqaPetEntity, LightEntity):
    """Custom LED colour of the purifier.

    "On" means a user-defined colour is active; "off" returns the ring to the automatic
    air-quality colour. The firmware exposes no brightness write, so brightness is read-only.
    """

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}  # noqa: RUF012

    @property
    def is_on(self) -> bool:
        """Return True if a custom colour is active."""
        return self.coordinator.data.purifier.led_custom

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the configured colour."""
        state = self.coordinator.data.purifier
        return (state.led_red, state.led_green, state.led_blue)

    @property
    def brightness(self) -> int:
        """Return the reported brightness scaled to 0..255."""
        return round(self.coordinator.data.purifier.led_brightness * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the custom colour, optionally with a new RGB value."""
        rgb: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        await self._async_send(self.coordinator.purifier_device.set_led(True, rgb))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Return to the automatic colour."""
        await self._async_send(self.coordinator.purifier_device.set_led(False))
