"""Base entity for all Klyqa Pet platforms."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from pyklyqa_pet import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

from .const import DOMAIN, MANUFACTURER
from .coordinator import KlyqaDeviceCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .hub import KlyqaPetHub


class KlyqaPetEntity(CoordinatorEntity[KlyqaDeviceCoordinator]):
    """Common behaviour: unique id, device info and command error handling."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KlyqaDeviceCoordinator, description: EntityDescription) -> None:
        """Initialise the entity from its description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.local_device_id}_{description.key}"
        info = coordinator.data.system_info if coordinator.data is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.local_device_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.product_name,
            model_id=coordinator.product_id or None,
            name=coordinator.device_name,
            serial_number=str(info.serial_number) if info and info.serial_number else None,
            sw_version=info.app_version if info and info.app_version else None,
            hw_version=str(info.hw_revision) if info and info.hw_revision else None,
        )

    async def _async_send(self, command: Coroutine[Any, Any, Any]) -> None:
        """Run a device command, translate library errors and refresh the coordinator."""
        device = self.coordinator.device_name
        try:
            await command
        except KlyqaAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"device": device},
            ) from err
        except KlyqaDeviceError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_rejected",
                translation_placeholders={"device": device, "error": str(err)},
            ) from err
        except KlyqaConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"device": device},
            ) from err
        await self.coordinator.async_request_refresh()


def async_setup_platform_entities(
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[KlyqaDeviceCoordinator], Iterable[Entity]],
) -> None:
    """Add entities for existing devices and for devices discovered later."""
    hub: KlyqaPetHub = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add(coordinator: KlyqaDeviceCoordinator) -> None:
        if coordinator.local_device_id in added:
            return
        added.add(coordinator.local_device_id)
        async_add_entities(factory(coordinator))

    entry.async_on_unload(hub.async_add_new_device_listener(_add))
    for coordinator in list(hub.coordinators.values()):
        _add(coordinator)
