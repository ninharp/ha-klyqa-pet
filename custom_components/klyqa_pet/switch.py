"""Switch platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator, KlyqaDeviceData
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KlyqaSwitchEntityDescription(SwitchEntityDescription):
    """Switch description with state extractor and command."""

    is_on_fn: Callable[[KlyqaDeviceData], bool]
    set_fn: Callable[[KlyqaDeviceCoordinator, bool], Coroutine[Any, Any, Any]]


def _welly_setting(key: str) -> KlyqaSwitchEntityDescription:
    return KlyqaSwitchEntityDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: bool(getattr(data.welly_settings, key)),
        set_fn=lambda coordinator, on: coordinator.welly_device.update_settings(**{key: on}),
    )


def _foody_setting(key: str) -> KlyqaSwitchEntityDescription:
    return KlyqaSwitchEntityDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: bool(getattr(data.foody_settings, key)),
        set_fn=lambda coordinator, on: coordinator.foody_device.update_settings(**{key: on}),
    )


WELLY_SWITCHES: tuple[KlyqaSwitchEntityDescription, ...] = (
    KlyqaSwitchEntityDescription(
        key="heating",
        translation_key="heating",
        is_on_fn=lambda data: data.welly.heating_enabled,
        set_fn=lambda coordinator, on: coordinator.welly_device.set_heating(enabled=on),
    ),
    _welly_setting("light_switch"),
    _welly_setting("ambient_light_switch"),
    _welly_setting("sensor_mode_light"),
    _welly_setting("alert_clean_tank_low"),
    _welly_setting("alert_dirty_tank_full"),
    _welly_setting("super_power_saving_mode"),
    _welly_setting("telemetry"),
)

FOODY_SWITCHES: tuple[KlyqaSwitchEntityDescription, ...] = (
    _foody_setting("app_led"),
    _foody_setting("app_pet_lock"),
    _foody_setting("beep_switch"),
    _foody_setting("feed_audio_enable"),
    _foody_setting("telemetry"),
)

PURIFIER_SWITCHES: tuple[KlyqaSwitchEntityDescription, ...] = (
    KlyqaSwitchEntityDescription(
        key="ionizer",
        translation_key="ionizer",
        is_on_fn=lambda data: data.purifier.ionizer_switch,
        set_fn=lambda coordinator, on: coordinator.purifier_device.set_ionizer(on=on),
    ),
    KlyqaSwitchEntityDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: data.purifier.child_lock,
        set_fn=lambda coordinator, on: coordinator.purifier_device.set_child_lock(on=on),
    ),
    KlyqaSwitchEntityDescription(
        key="key_tone",
        translation_key="key_tone",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: data.purifier.key_tone,
        set_fn=lambda coordinator, on: coordinator.purifier_device.set_key_tone(on=on),
    ),
)

SWITCHES_BY_TYPE: dict[DeviceType, tuple[KlyqaSwitchEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_SWITCHES,
    DeviceType.FOODY: FOODY_SWITCHES,
    DeviceType.AIRPURIFIER: PURIFIER_SWITCHES,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaSwitch]:
        return [
            KlyqaSwitch(coordinator, description)
            for description in SWITCHES_BY_TYPE[coordinator.device_type]
        ]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaSwitch(KlyqaPetEntity, SwitchEntity):
    """A boolean setting of a Klyqa device."""

    entity_description: KlyqaSwitchEntityDescription

    @property
    def is_on(self) -> bool:
        """Return the current state."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_send(self.entity_description.set_fn(self.coordinator, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_send(self.entity_description.set_fn(self.coordinator, False))
