"""Time platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
import datetime
from typing import Any

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .coordinator import KlyqaDeviceCoordinator
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class KlyqaTimeEntityDescription(TimeEntityDescription):
    """Time description with value extractor and command."""

    value_fn: Callable[[KlyqaDeviceCoordinator], datetime.time]
    set_fn: Callable[[KlyqaDeviceCoordinator, datetime.time], Coroutine[Any, Any, Any]]


FOODY_TIMES: tuple[KlyqaTimeEntityDescription, ...] = (
    KlyqaTimeEntityDescription(
        key="sleep_start",
        translation_key="sleep_start",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.foody_timers.sleep_mode.start,
        # Only `start` comes from this entity; `end`, the weekday mask and the enabled
        # flag are set elsewhere (the app, the `sleep_mode` switch, or the other `time`
        # entity) and must survive untouched, so the write is built from the
        # coordinator's own cached sleep mode via `replace`, not from scratch.
        set_fn=lambda coordinator, value: coordinator.foody_device.set_sleep_mode(
            replace(coordinator.data.foody_timers.sleep_mode, start=value)
        ),
    ),
    KlyqaTimeEntityDescription(
        key="sleep_end",
        translation_key="sleep_end",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.data.foody_timers.sleep_mode.end,
        set_fn=lambda coordinator, value: coordinator.foody_device.set_sleep_mode(
            replace(coordinator.data.foody_timers.sleep_mode, end=value)
        ),
    ),
)

TIMES_BY_TYPE: dict[DeviceType, tuple[KlyqaTimeEntityDescription, ...]] = {
    DeviceType.WELLY: (),
    DeviceType.FOODY: FOODY_TIMES,
    DeviceType.AIRPURIFIER: (),
    DeviceType.STRYPE: (),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up times for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaTime]:
        return [
            KlyqaTime(coordinator, description)
            for description in TIMES_BY_TYPE[coordinator.device_type]
        ]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaTime(KlyqaPetEntity, TimeEntity):
    """A time-of-day setting of a Klyqa device."""

    entity_description: KlyqaTimeEntityDescription

    @property
    def native_value(self) -> datetime.time:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_value(self, value: datetime.time) -> None:
        """Send the new value to the device."""
        await self._async_send(self.entity_description.set_fn(self.coordinator, value))
