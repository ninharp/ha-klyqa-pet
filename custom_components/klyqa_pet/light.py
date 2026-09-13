"""Light platform for the Klyqa air purifier LED ring and the Strype LED strip."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.components.light.const import ColorMode, LightEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType
from pyklyqa_pet.const import STRYPE_MAX_KELVIN, STRYPE_MIN_KELVIN

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1

LED_DESCRIPTION = LightEntityDescription(key="led", translation_key="led")
STRIP_DESCRIPTION = LightEntityDescription(key="strip", translation_key="strip")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the LED light for every air purifier and the strip for every Strype."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[LightEntity]:
        if coordinator.device_type is DeviceType.AIRPURIFIER:
            return [KlyqaPurifierLight(coordinator, LED_DESCRIPTION)]
        if coordinator.device_type is DeviceType.STRYPE:
            return [KlyqaStrypeLight(coordinator, STRIP_DESCRIPTION)]
        return []

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaPurifierLight(KlyqaPetEntity, LightEntity):
    """Custom LED colour and brightness of the purifier.

    "On" means a user-defined colour is active; "off" returns the ring to the automatic
    air-quality colour. Brightness (0..100 %, mapped from Home Assistant's 0..255 range)
    can be set together with, or independently of, the colour.
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
        """Enable the custom colour, optionally with a new RGB value and/or brightness."""
        rgb: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        brightness: int | None = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
        await self._async_send(self.coordinator.purifier_device.set_led(True, rgb, brightness))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Return to the automatic colour."""
        await self._async_send(self.coordinator.purifier_device.set_led(False))


class KlyqaStrypeLight(KlyqaPetEntity, LightEntity):
    """The Strype LED strip: brightness, RGB colour and colour temperature."""

    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}  # noqa: RUF012
    _attr_supported_features = LightEntityFeature.TRANSITION
    _attr_min_color_temp_kelvin = STRYPE_MIN_KELVIN
    _attr_max_color_temp_kelvin = STRYPE_MAX_KELVIN

    @property
    def is_on(self) -> bool:
        """Return True if the strip is lit."""
        return self.coordinator.data.strype.power_on

    @property
    def color_mode(self) -> ColorMode:
        """Follow the mode the firmware reports; `cmd` keeps the last colour mode."""
        return ColorMode.COLOR_TEMP if self.coordinator.data.strype.mode == "cct" else ColorMode.RGB

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the current RGB colour."""
        return self.coordinator.data.strype.rgb

    @property
    def color_temp_kelvin(self) -> int:
        """Return the current colour temperature in Kelvin."""
        return self.coordinator.data.strype.temperature_kelvin

    @property
    def brightness(self) -> int:
        """Return brightness on Home Assistant's 0..255 scale."""
        return round(self.coordinator.data.strype.brightness_percent * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally setting colour, colour temperature or brightness."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        transition = kwargs.get(ATTR_TRANSITION)
        await self._async_send(
            self.coordinator.strype_device.set_state(
                power_on=True,
                rgb=kwargs.get(ATTR_RGB_COLOR),
                temperature_kelvin=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
                brightness_percent=None if brightness is None else round(brightness * 100 / 255),
                transition_ms=None if transition is None else int(transition * 1000),
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the strip off."""
        transition = kwargs.get(ATTR_TRANSITION)
        await self._async_send(
            self.coordinator.strype_device.set_state(
                power_on=False,
                transition_ms=None if transition is None else int(transition * 1000),
            )
        )
