"""Base entity for all Klyqa Pet platforms."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from pyklyqa_pet import (
    FoodySettings,
    FoodyTimers,
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDeviceError,
    KlyqaError,
    StrypeState,
    WellySettings,
)
from pyklyqa_pet.welly_timers import WellyTimers

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

    def _command_error(self, err: KlyqaError) -> HomeAssistantError:
        """Translate a library error into the message the user is shown."""
        placeholders = {"device": self.coordinator.device_name}
        if isinstance(err, KlyqaAuthError):
            key = "auth_failed"
        elif isinstance(err, KlyqaDeviceError):
            key = "device_rejected"
            placeholders["error"] = str(err)
        else:
            key = "cannot_connect"
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    async def _async_send(
        self, command: Coroutine[Any, Any, Any], *, writes_timers: bool = False
    ) -> None:
        """Run a device command, translate library errors and publish or refresh.

        `writes_timers` marks the commands that write the Foody's or the Welly's timer
        document. A rejected one still needs handling, because the firmware mutates its
        own copy before the step that can fail - the sleep branch stores enable, the
        weekday mask and both times and only then calls feeder_com_send_sleep_mode_ctrl,
        exactly as the schedule branches do (device_timers.c). So a failed write may
        already have moved the device while the published document still shows the old
        window, and nothing else would notice: the success path publishes rather than
        refreshes. Dropping the cached document leaves the re-read to the next scheduled
        poll; as in the services, the failure path deliberately does not force a refresh
        at a device that has just refused a request.
        """
        try:
            result = await command
        except (KlyqaAuthError, KlyqaDeviceError, KlyqaConnectionError) as err:
            if writes_timers:
                self.coordinator.mark_timers_stale()
            raise self._command_error(err) from err
        if isinstance(result, StrypeState):
            # A Strype write answers with the very same status message a read does, and
            # the library has already merged it onto the coordinator's previous state
            # (the caller passes it in as `previous=`). It is therefore a complete
            # picture: publish it instead of polling the device again. There is no state
            # GET to re-read from, so a refresh would only repeat this same request.
            self.coordinator.async_publish_strype_state(result)
            return
        if isinstance(result, WellySettings | FoodySettings):
            # A settings write already returns the fresh settings; mark the coordinator's
            # cache stale so the refresh below reloads it instead of reusing the copy
            # from before the write (see KlyqaDeviceCoordinator.mark_settings_stale).
            self.coordinator.mark_settings_stale()
        if isinstance(result, FoodyTimers | WellyTimers):
            # A timer write (Foody schedule/sleep mode, or Welly quiet-time/descaling/
            # water-change) is answered with the complete, freshly serialised timer
            # document, so publish it instead of asking for a refresh. That matters
            # beyond saving a request: the sleep-mode switch and the two sleep-window
            # `time` entities each build their write from the cached document via
            # `replace`, and `async_request_refresh` is debounced - in a burst of writes
            # only the first one would actually re-read, so every later write would
            # still be built from the pre-burst snapshot and silently revert its
            # predecessor. Publishing makes each write authoritative at once.
            self.coordinator.async_publish_timers(result)
            return
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
