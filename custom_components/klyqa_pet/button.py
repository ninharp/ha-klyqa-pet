"""Button platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KlyqaButtonEntityDescription(ButtonEntityDescription):
    """Button description with the command to run."""

    press_fn: Callable[[KlyqaDeviceCoordinator], Coroutine[Any, Any, Any]]


COMMON_BUTTONS: tuple[KlyqaButtonEntityDescription, ...] = (
    KlyqaButtonEntityDescription(
        key="restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Generic SDK reboot (PUT system/command) for every device type.
        press_fn=lambda coordinator: coordinator.device.reboot(),
    ),
)

WELLY_BUTTONS: tuple[KlyqaButtonEntityDescription, ...] = (
    KlyqaButtonEntityDescription(
        key="start_descaling",
        translation_key="start_descaling",
        press_fn=lambda coordinator: coordinator.welly_device.set_descaling(True),
    ),
    KlyqaButtonEntityDescription(
        key="stop_descaling",
        translation_key="stop_descaling",
        press_fn=lambda coordinator: coordinator.welly_device.set_descaling(False),
    ),
)

FOODY_BUTTONS: tuple[KlyqaButtonEntityDescription, ...] = (
    KlyqaButtonEntityDescription(
        key="dispense_food",
        translation_key="dispense_food",
        press_fn=lambda coordinator: coordinator.foody_device.dispense(
            coordinator.dispense_portions
        ),
    ),
    KlyqaButtonEntityDescription(
        key="play_voice_recording",
        translation_key="play_voice_recording",
        press_fn=lambda coordinator: coordinator.foody_device.play_voice_recording(),
    ),
    KlyqaButtonEntityDescription(
        key="query_bowl_weight",
        translation_key="query_bowl_weight",
        press_fn=lambda coordinator: coordinator.foody_device.query_realtime_weight(),
    ),
)

BUTTONS_BY_TYPE: dict[DeviceType, tuple[KlyqaButtonEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_BUTTONS,
    DeviceType.FOODY: FOODY_BUTTONS,
    DeviceType.AIRPURIFIER: (),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaButton]:
        descriptions = COMMON_BUTTONS + BUTTONS_BY_TYPE[coordinator.device_type]
        return [KlyqaButton(coordinator, description) for description in descriptions]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaButton(KlyqaPetEntity, ButtonEntity):
    """A one-shot action on a Klyqa device."""

    entity_description: KlyqaButtonEntityDescription

    async def async_press(self) -> None:
        """Run the action."""
        await self._async_send(self.entity_description.press_fn(self.coordinator))
