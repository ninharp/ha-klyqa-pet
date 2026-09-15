"""Services of the Klyqa Pet integration: the schedule lists of the Foody and Welly.

The Foody holds up to MAX_FEEDING_SCHEDULES feeding schedules, the Welly up to
MAX_WATER_CHANGE_ENTRIES water-change entries, each addressed by an id. There is no
entity shape that fits either list (a variable-length list of records, created and
deleted by the user), so both are exposed as three actions apiece, alongside the
read-only sensors that render the current list.
"""

from __future__ import annotations

from collections.abc import Coroutine
import dataclasses
from typing import TYPE_CHECKING, Any, Final, Literal

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from pyklyqa_pet import (
    DeviceType,
    FeedingSchedule,
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDeviceError,
)
from pyklyqa_pet.foody_timers import MAX_DURATION_SEC, MAX_FEEDING_SCHEDULES, MAX_PORTIONS
from pyklyqa_pet.welly_timers import MAX_WATER_CHANGE_ENTRIES, WaterChangeEntry

from .const import DOMAIN, WEEKDAY_KEYS
from .coordinator import KlyqaDeviceCoordinator

if TYPE_CHECKING:
    from .hub import KlyqaPetHub

SERVICE_ADD_FEEDING_SCHEDULE: Final = "add_feeding_schedule"
SERVICE_SET_FEEDING_SCHEDULE: Final = "set_feeding_schedule"
SERVICE_DELETE_FEEDING_SCHEDULE: Final = "delete_feeding_schedule"
SERVICE_ADD_WATER_CHANGE: Final = "add_water_change"
SERVICE_SET_WATER_CHANGE: Final = "set_water_change"
SERVICE_DELETE_WATER_CHANGE: Final = "delete_water_change"

ATTR_DEVICE_ID: Final = "device_id"
ATTR_SCHEDULE_ID: Final = "schedule_id"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_TIME: Final = "time"
ATTR_PORTIONS: Final = "portions"
ATTR_DURATION: Final = "duration"
ATTR_WEEKDAYS: Final = "weekdays"
ATTR_ENABLED: Final = "enabled"
ATTR_SKIP_ONCE: Final = "skip_once"
ATTR_FRESH_FOOD_MODE: Final = "fresh_food_mode"
ATTR_AUTO_PLAY_VOICE: Final = "auto_play_voice"

_PORTIONS = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PORTIONS))
_WEEKDAYS = vol.All(cv.ensure_list, vol.Length(min=1), [vol.In(WEEKDAY_KEYS)])
_SCHEDULE_ID = vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_FEEDING_SCHEDULES - 1))
_DURATION = vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION_SEC))

# Every flag is optional in both write services: `add` falls back to the defaults below,
# `set` leaves anything the caller omitted exactly as the device has it.
_OPTIONAL_FIELDS: Final[dict[Any, Any]] = {
    vol.Optional(ATTR_WEEKDAYS): _WEEKDAYS,
    vol.Optional(ATTR_DURATION): _DURATION,
    vol.Optional(ATTR_ENABLED): cv.boolean,
    vol.Optional(ATTR_SKIP_ONCE): cv.boolean,
    vol.Optional(ATTR_FRESH_FOOD_MODE): cv.boolean,
    vol.Optional(ATTR_AUTO_PLAY_VOICE): cv.boolean,
}

ADD_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_TIME): cv.time,
        vol.Required(ATTR_PORTIONS): _PORTIONS,
        **_OPTIONAL_FIELDS,
    }
)

SET_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_SCHEDULE_ID): _SCHEDULE_ID,
        vol.Optional(ATTR_TIME): cv.time,
        vol.Optional(ATTR_PORTIONS): _PORTIONS,
        **_OPTIONAL_FIELDS,
    }
)

DELETE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_SCHEDULE_ID): _SCHEDULE_ID,
    }
)

# The Welly's entries live in a fixed array of MAX_WATER_CHANGE_ENTRIES slots on the
# MCU, which draws their ids from that same range, so an id outside it can never exist.
# The id is the MCU's own numbering, not the entry's position in the list the device
# reports: deleting an entry leaves a gap rather than renumbering the rest.
_ENTRY_ID = vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_WATER_CHANGE_ENTRIES - 1))

ADD_WATER_CHANGE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_TIME): cv.time,
        vol.Optional(ATTR_WEEKDAYS): _WEEKDAYS,
        vol.Optional(ATTR_ENABLED): cv.boolean,
    }
)

SET_WATER_CHANGE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ENTRY_ID): _ENTRY_ID,
        vol.Optional(ATTR_TIME): cv.time,
        vol.Optional(ATTR_WEEKDAYS): _WEEKDAYS,
        vol.Optional(ATTR_ENABLED): cv.boolean,
    }
)

DELETE_WATER_CHANGE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ENTRY_ID): _ENTRY_ID,
    }
)

# Defaults of a newly created schedule: on, not skipped, every day, mode flag off,
# silent, and no duration - which is what every captured schedule carries.
DEFAULT_ENABLED: Final = True
DEFAULT_SKIP_ONCE: Final = False
DEFAULT_FRESH_FOOD_MODE: Final = False
DEFAULT_AUTO_PLAY_VOICE: Final = False
DEFAULT_DURATION_SEC: Final = 0


def _decode_weekdays(keys: list[str]) -> frozenset[int]:
    """Turn the service's weekday keys into the library's day indices."""
    return frozenset(WEEKDAY_KEYS.index(key) for key in keys)


# The message for a target of the wrong kind names what the action needs, so each
# device type carries its own key. Only the two types that own schedule lists have one,
# and the parameter is typed to them - a third would have to add its key here.
_WrongTypeDevice = Literal[DeviceType.FOODY, DeviceType.WELLY]

_WRONG_TYPE_KEYS: Final[dict[_WrongTypeDevice, str]] = {
    DeviceType.FOODY: "not_a_foody",
    DeviceType.WELLY: "not_a_welly",
}


def _async_resolve_coordinator(
    hass: HomeAssistant, device_id: str, device_type: _WrongTypeDevice
) -> KlyqaDeviceCoordinator:
    """Return the coordinator of that device type behind a Home Assistant device id.

    Services are targeted at a device-registry id, while the hub keys its coordinators
    by the device's `local_device_id`; the registry entry's `(DOMAIN, local_device_id)`
    identifier and its config entries bridge the two.
    """
    registry = dr.async_get(hass)
    device_entry = registry.async_get(device_id)
    if device_entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )
    name = device_entry.name_by_user or device_entry.name or device_id
    local_device_id = next(
        (identifier for domain, identifier in device_entry.identifiers if domain == DOMAIN),
        None,
    )
    if local_device_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_klyqa",
            translation_placeholders={"device": name},
        )
    coordinator: KlyqaDeviceCoordinator | None = None
    for entry_id in device_entry.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            continue
        hub: KlyqaPetHub = entry.runtime_data
        if (coordinator := hub.coordinators.get(local_device_id)) is not None:
            break
    if coordinator is None:
        # Either no loaded entry owns the device, or the device is known but has never
        # been reached (no host yet), so no coordinator exists to talk to it.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_available",
            translation_placeholders={"device": name},
        )
    if coordinator.device_type is not device_type:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=_WRONG_TYPE_KEYS[device_type],
            translation_placeholders={"device": coordinator.device_name},
        )
    return coordinator


async def _async_device_call(
    coordinator: KlyqaDeviceCoordinator, command: Coroutine[Any, Any, Any]
) -> Any:
    """Await a device call and translate the library's errors, as entities do."""
    device = coordinator.device_name
    try:
        return await command
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


async def _async_read_schedules(
    coordinator: KlyqaDeviceCoordinator,
) -> tuple[FeedingSchedule, ...]:
    """Read the schedules straight from the device, never from the coordinator's cache.

    The schedule list lives in the ESP's shadow of the feeder's MCU and the firmware
    offers no way to re-derive it, so a slot id that was cached at the last poll may by
    now address a different schedule than the user means. Every service therefore starts
    with a fresh read and validates the id against that.
    """
    timers = await _async_device_call(coordinator, coordinator.foody_device.get_timers())
    schedules: tuple[FeedingSchedule, ...] = timers.schedules
    return schedules


def _find(schedules: tuple[FeedingSchedule, ...], schedule_id: int, device: str) -> FeedingSchedule:
    """Return the schedule with that id, or explain that the device has no such slot."""
    for schedule in schedules:
        if schedule.schedule_id == schedule_id:
            return schedule
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_schedule",
        translation_placeholders={"device": device, "schedule_id": str(schedule_id)},
    )


async def _async_write(
    coordinator: KlyqaDeviceCoordinator, command: Coroutine[Any, Any, Any]
) -> Any:
    """Await a timer write, dropping the cached document even when the write fails.

    A rejected write can still have changed the device. On the Foody the firmware
    mutates its own shadow *before* the step that can fail: a delete clears the slot and
    only then tells the MCU, and a set stores the entry and only then sends it on
    (device_timers.c). On the Welly nothing local changes at all - the entry goes
    straight to the fountain's MCU, which may have accepted it even when the ESP answers
    with an error. Either way, keeping the pre-write document would leave the
    `feeding_schedules` or `water_change_schedules` sensor listing an entry that is
    already gone. Marking the cache stale lets the
    next scheduled poll re-read it; the failure path deliberately does not force a
    refresh, which would only put another request to a device that has just refused one.
    """
    try:
        return await _async_device_call(coordinator, command)
    except HomeAssistantError:
        coordinator.mark_timers_stale()
        raise


async def _async_finish(coordinator: KlyqaDeviceCoordinator) -> None:
    """Make the change visible to the schedule sensor without waiting for the next poll."""
    coordinator.mark_timers_stale()
    await coordinator.async_request_refresh()


async def _async_add_feeding_schedule(call: ServiceCall) -> None:
    """Create a feeding schedule in the lowest free slot."""
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.FOODY)
    # The free slot is derived from the list that was just read, so nothing else may
    # write to this device between the read and the write that claims the slot.
    async with coordinator.write_lock:
        schedules = await _async_read_schedules(coordinator)
        used = {schedule.schedule_id for schedule in schedules}
        schedule_id = next(
            (slot for slot in range(MAX_FEEDING_SCHEDULES) if slot not in used), None
        )
        if schedule_id is None:
            # Claiming a free slot is this service's job, so a full device is answered
            # here with a clear message instead of the firmware's terse rejection.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_free_schedule_slot",
                translation_placeholders={
                    "device": coordinator.device_name,
                    "maximum": str(MAX_FEEDING_SCHEDULES),
                },
            )
        weekdays = call.data.get(ATTR_WEEKDAYS)
        schedule = FeedingSchedule(
            schedule_id=schedule_id,
            enabled=call.data.get(ATTR_ENABLED, DEFAULT_ENABLED),
            skip_once=call.data.get(ATTR_SKIP_ONCE, DEFAULT_SKIP_ONCE),
            execution_time=call.data[ATTR_TIME],
            weekdays=_decode_weekdays(weekdays) if weekdays else frozenset(range(7)),
            portions=call.data[ATTR_PORTIONS],
            # The firmware only bounds this to 0-10800 and forwards it to the MCU; what
            # the feeder makes of it is not verified, and every captured schedule
            # carries 0, which stays the default.
            total_duration_sec=call.data.get(ATTR_DURATION, DEFAULT_DURATION_SEC),
            fresh_food_mode=call.data.get(ATTR_FRESH_FOOD_MODE, DEFAULT_FRESH_FOOD_MODE),
            auto_play_voice=call.data.get(ATTR_AUTO_PLAY_VOICE, DEFAULT_AUTO_PLAY_VOICE),
        )
        await _async_write(
            coordinator, coordinator.foody_device.set_schedule(schedule, create=True)
        )
        await _async_finish(coordinator)


async def _async_set_feeding_schedule(call: ServiceCall) -> None:
    """Change an existing feeding schedule, leaving omitted fields as they are."""
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.FOODY)
    schedule_id: int = call.data[ATTR_SCHEDULE_ID]
    # The write is the schedule that was just read with a few fields replaced, so a
    # change landing in between would be silently dropped by this one.
    async with coordinator.write_lock:
        schedules = await _async_read_schedules(coordinator)
        existing = _find(schedules, schedule_id, coordinator.device_name)
        changes: dict[str, Any] = {}
        if (execution_time := call.data.get(ATTR_TIME)) is not None:
            changes["execution_time"] = execution_time
        if (portions := call.data.get(ATTR_PORTIONS)) is not None:
            changes["portions"] = portions
        if (weekdays := call.data.get(ATTR_WEEKDAYS)) is not None:
            changes["weekdays"] = _decode_weekdays(weekdays)
        if (duration := call.data.get(ATTR_DURATION)) is not None:
            changes["total_duration_sec"] = duration
        for attribute in (
            ATTR_ENABLED,
            ATTR_SKIP_ONCE,
            ATTR_FRESH_FOOD_MODE,
            ATTR_AUTO_PLAY_VOICE,
        ):
            if attribute in call.data:
                changes[attribute] = call.data[attribute]
        schedule = dataclasses.replace(existing, **changes)
        await _async_write(
            coordinator, coordinator.foody_device.set_schedule(schedule, create=False)
        )
        await _async_finish(coordinator)


async def _async_delete_feeding_schedule(call: ServiceCall) -> None:
    """Delete a feeding schedule by its slot id."""
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.FOODY)
    schedule_id: int = call.data[ATTR_SCHEDULE_ID]
    # The id is only known to mean what the user meant for as long as the list that was
    # just read still stands, so the delete belongs inside the same lock.
    async with coordinator.write_lock:
        schedules = await _async_read_schedules(coordinator)
        _find(schedules, schedule_id, coordinator.device_name)
        await _async_write(coordinator, coordinator.foody_device.delete_schedule(schedule_id))
        await _async_finish(coordinator)


async def _async_read_water_changes(
    coordinator: KlyqaDeviceCoordinator,
) -> tuple[WaterChangeEntry, ...]:
    """Read the water-change entries straight from the device, never from the cache.

    Same reasoning as the feeding schedules: the list lives in the ESP's shadow of the
    fountain's MCU, an entry id is the MCU's own numbering rather than a stable identity
    (a freed id may be handed to an unrelated entry next), and a cached id may by now
    address a different entry than the user means.
    """
    timers = await _async_device_call(coordinator, coordinator.welly_device.get_timers())
    entries: tuple[WaterChangeEntry, ...] = timers.water_changes
    return entries


def _find_entry(
    entries: tuple[WaterChangeEntry, ...], entry_id: int, device: str
) -> WaterChangeEntry:
    """Return the entry with that id, or explain that the device has no such entry."""
    for entry in entries:
        if entry.entry_id == entry_id:
            return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_water_change",
        translation_placeholders={"device": device, "entry_id": str(entry_id)},
    )


async def _async_add_water_change(call: ServiceCall) -> None:
    """Create a water-change schedule; the MCU assigns its id.

    Unlike the Foody's `add`, this picks no slot: the firmware forwards the entry to
    the MCU without an id and the MCU numbers it, reporting the id back asynchronously.
    The new entry may therefore not yet appear in the read that follows the write, and
    the service cannot tell the caller which id was created - the `water_change_schedules`
    sensor lists them once the device has caught up.
    """
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.WELLY)
    # The cap is checked against the list that was just read, so nothing else may write
    # to this device between that read and the write that fills the last free entry.
    async with coordinator.write_lock:
        entries = await _async_read_water_changes(coordinator)
        if len(entries) >= MAX_WATER_CHANGE_ENTRIES:
            # A full device is answered here with a clear message instead of the
            # firmware's terse rejection.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_free_water_change_slot",
                translation_placeholders={
                    "device": coordinator.device_name,
                    "maximum": str(MAX_WATER_CHANGE_ENTRIES),
                },
            )
        weekdays = call.data.get(ATTR_WEEKDAYS)
        entry = WaterChangeEntry(
            # Ignored: `add` serialises the entry without its id (to_dict(include_id=False)).
            entry_id=0,
            enabled=call.data.get(ATTR_ENABLED, DEFAULT_ENABLED),
            start=call.data[ATTR_TIME],
            weekdays=_decode_weekdays(weekdays) if weekdays else frozenset(range(7)),
        )
        await _async_write(coordinator, coordinator.welly_device.add_water_change(entry))
        await _async_finish(coordinator)


async def _async_set_water_change(call: ServiceCall) -> None:
    """Change an existing water-change schedule, leaving omitted fields as they are."""
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.WELLY)
    entry_id: int = call.data[ATTR_ENTRY_ID]
    # The write is the entry that was just read with a few fields replaced, so a change
    # landing in between would be silently dropped by this one.
    async with coordinator.write_lock:
        entries = await _async_read_water_changes(coordinator)
        existing = _find_entry(entries, entry_id, coordinator.device_name)
        changes: dict[str, Any] = {}
        if (start := call.data.get(ATTR_TIME)) is not None:
            changes["start"] = start
        if (weekdays := call.data.get(ATTR_WEEKDAYS)) is not None:
            changes["weekdays"] = _decode_weekdays(weekdays)
        if ATTR_ENABLED in call.data:
            changes["enabled"] = call.data[ATTR_ENABLED]
        entry = dataclasses.replace(existing, **changes)
        await _async_write(coordinator, coordinator.welly_device.set_water_change(entry))
        await _async_finish(coordinator)


async def _async_delete_water_change(call: ServiceCall) -> None:
    """Delete a water-change schedule by its entry id.

    One id per call: the firmware also accepts an array, but a partial failure across
    one has no legible error story, so it is out of scope.
    """
    coordinator = _async_resolve_coordinator(call.hass, call.data[ATTR_DEVICE_ID], DeviceType.WELLY)
    entry_id: int = call.data[ATTR_ENTRY_ID]
    # The id only means what the user meant for as long as the list that was just read
    # still stands, so the delete belongs inside the same lock.
    async with coordinator.write_lock:
        entries = await _async_read_water_changes(coordinator)
        _find_entry(entries, entry_id, coordinator.device_name)
        await _async_write(coordinator, coordinator.welly_device.delete_water_change(entry_id))
        await _async_finish(coordinator)


_SERVICES: Final = (
    (SERVICE_ADD_FEEDING_SCHEDULE, _async_add_feeding_schedule, ADD_SCHEMA),
    (SERVICE_SET_FEEDING_SCHEDULE, _async_set_feeding_schedule, SET_SCHEMA),
    (SERVICE_DELETE_FEEDING_SCHEDULE, _async_delete_feeding_schedule, DELETE_SCHEMA),
    (SERVICE_ADD_WATER_CHANGE, _async_add_water_change, ADD_WATER_CHANGE_SCHEMA),
    (SERVICE_SET_WATER_CHANGE, _async_set_water_change, SET_WATER_CHANGE_SCHEMA),
    (SERVICE_DELETE_WATER_CHANGE, _async_delete_water_change, DELETE_WATER_CHANGE_SCHEMA),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the feeding-schedule and water-change services.

    Called from async_setup, so the actions exist as soon as the integration is loaded
    and stay for the lifetime of Home Assistant - independent of how many config entries
    there are and whether any of them is currently loaded. A call always resolves its
    target device at call time and answers with `device_not_available` when no loaded
    entry owns it, which is the clear message an unregistered action could not give.
    """
    for name, handler, schema in _SERVICES:
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)
