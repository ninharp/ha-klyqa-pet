"""Tests for the Foody feeding-schedule services."""

import asyncio
from datetime import time
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol
import yaml

from custom_components.klyqa_pet.const import DOMAIN, WEEKDAY_KEYS
from custom_components.klyqa_pet.coordinator import KlyqaDeviceCoordinator
from custom_components.klyqa_pet.services import (
    ADD_SCHEMA,
    DELETE_SCHEMA,
    SERVICE_ADD_FEEDING_SCHEDULE,
    SERVICE_DELETE_FEEDING_SCHEDULE,
    SERVICE_SET_FEEDING_SCHEDULE,
    SET_SCHEMA,
)
from pyklyqa_pet import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError
from pyklyqa_pet.foody_timers import (
    MAX_DURATION_SEC,
    MAX_FEEDING_SCHEDULES,
    MAX_PORTIONS,
    FoodyTimers,
)

from .conftest import FOODY_ID, WELLY_ID, load_json, setup_integration


def make_timers(count: int) -> FoodyTimers:
    """Build a timer document with `count` consecutive schedules."""
    document = load_json("foody_timers.json")
    template = document["schedules"][0]
    document["schedules"] = [
        {**template, "schedule_id": index, "execution_time": 700 + index} for index in range(count)
    ]
    return FoodyTimers.from_dict(document)


@pytest.fixture
async def integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    # The sensor platform is the cheapest way to get device-registry entries, which is
    # what the services resolve their `device_id` against.
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)


def device_id_of(hass: HomeAssistant, entry: MockConfigEntry, local_device_id: str) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, local_device_id), entry.entry_id
    )
    assert device is not None
    return device.id


@pytest.fixture
def foody_device_id(
    hass: HomeAssistant, integration: None, mock_config_entry: MockConfigEntry
) -> str:
    return device_id_of(hass, mock_config_entry, FOODY_ID)


@pytest.fixture
def welly_device_id(
    hass: HomeAssistant, integration: None, mock_config_entry: MockConfigEntry
) -> str:
    return device_id_of(hass, mock_config_entry, WELLY_ID)


async def call(hass: HomeAssistant, service: str, data: dict[str, Any]) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_delete_rereads_before_writing(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """The ESP shadow cannot be re-derived from the MCU, so ids are re-read, never cached.

    The device now holds slot 3 where the coordinator's cache (filled at setup from
    foody_timers.json) still has slot 0, so only a service that re-reads can delete 3 -
    and only one that does not trust the cache refuses 0.
    """
    document = load_json("foody_timers.json")
    document["schedules"][0]["schedule_id"] = 3
    mock_foody.get_timers.return_value = FoodyTimers.from_dict(document)
    mock_foody.reset_mock()

    await call(
        hass,
        SERVICE_DELETE_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "schedule_id": 3},
    )
    # The read precedes the write; the second read is the refresh that follows it.
    assert [name for name, *_ in mock_foody.mock_calls][:2] == ["get_timers", "delete_schedule"]
    assert mock_foody.delete_schedule.await_args.args == (3,)

    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )
    assert err.value.translation_key == "unknown_schedule"


async def test_add_surfaces_a_full_device(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """A rejection from the firmware reaches the user as a HomeAssistantError."""
    mock_foody.set_schedule.side_effect = KlyqaDeviceError(["No free schedule slot available"])
    with pytest.raises(HomeAssistantError, match="No free schedule slot available"):
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "time": "07:00:00", "portions": 2},
        )


async def test_set_rejects_an_unknown_schedule_id(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_SET_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 7, "portions": 3},
        )
    assert err.value.translation_key == "unknown_schedule"
    mock_foody.set_schedule.assert_not_awaited()


async def test_delete_rejects_an_unknown_schedule_id(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 7},
        )
    assert err.value.translation_key == "unknown_schedule"
    mock_foody.delete_schedule.assert_not_awaited()


async def test_a_service_on_a_welly_is_rejected(
    hass: HomeAssistant, mock_welly: MagicMock, welly_device_id: str
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": welly_device_id, "time": "07:00:00", "portions": 1},
        )
    assert err.value.translation_key == "not_a_foody"


async def test_an_unknown_device_is_rejected(hass: HomeAssistant, integration: None) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": "does-not-exist", "time": "07:00:00", "portions": 1},
        )
    assert err.value.translation_key == "device_not_found"


async def test_a_device_of_another_integration_is_rejected(
    hass: HomeAssistant, integration: None
) -> None:
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "thing")}
    )
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": device.id, "time": "07:00:00", "portions": 1},
        )
    assert err.value.translation_key == "device_not_klyqa"


async def test_a_device_of_an_unloaded_entry_is_rejected(
    hass: HomeAssistant, integration: None
) -> None:
    """A Klyqa device whose entry is not loaded has no coordinator to talk to."""
    other = MockConfigEntry(domain=DOMAIN, unique_id="local")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={(DOMAIN, "AABBCCDDEEFF")}
    )
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": device.id, "time": "07:00:00", "portions": 1},
        )
    assert err.value.translation_key == "device_not_available"


async def test_add_uses_the_defaults_for_omitted_fields(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    await call(
        hass,
        SERVICE_ADD_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "time": "07:05:00", "portions": 2},
    )
    schedule = mock_foody.set_schedule.await_args.args[0]
    assert mock_foody.set_schedule.await_args.kwargs == {"create": True}
    assert schedule.execution_time == time(7, 5)
    assert schedule.portions == 2
    assert schedule.weekdays == frozenset(range(7))
    assert schedule.enabled is True
    assert schedule.skip_once is False
    assert schedule.fresh_food_mode is False
    assert schedule.auto_play_voice is False
    assert schedule.total_duration_sec == 0


async def test_add_takes_every_field(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    await call(
        hass,
        SERVICE_ADD_FEEDING_SCHEDULE,
        {
            "device_id": foody_device_id,
            "time": "18:45:00",
            "portions": 4,
            "weekdays": ["mon", "sat"],
            "enabled": False,
            "skip_once": True,
            "fresh_food_mode": True,
            "auto_play_voice": True,
            "duration": 900,
        },
    )
    schedule = mock_foody.set_schedule.await_args.args[0]
    assert schedule.execution_time == time(18, 45)
    assert schedule.portions == 4
    assert schedule.weekdays == frozenset({1, 6})
    assert schedule.enabled is False
    assert schedule.skip_once is True
    assert schedule.fresh_food_mode is True
    assert schedule.auto_play_voice is True
    assert schedule.total_duration_sec == 900


async def test_set_leaves_the_duration_alone_unless_it_is_given(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """`duration` is bounded by the library's limit and omitted means unchanged."""
    document = load_json("foody_timers.json")
    document["schedules"][0]["total_duration_sec"] = 600
    mock_foody.get_timers.return_value = FoodyTimers.from_dict(document)

    await call(
        hass,
        SERVICE_SET_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "schedule_id": 0, "portions": 3},
    )
    assert mock_foody.set_schedule.await_args.args[0].total_duration_sec == 600

    await call(
        hass,
        SERVICE_SET_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "schedule_id": 0, "duration": 0},
    )
    assert mock_foody.set_schedule.await_args.args[0].total_duration_sec == 0

    with pytest.raises(vol.Invalid):
        await call(
            hass,
            SERVICE_SET_FEEDING_SCHEDULE,
            {
                "device_id": foody_device_id,
                "schedule_id": 0,
                "duration": MAX_DURATION_SEC + 1,
            },
        )


async def test_add_picks_the_lowest_free_slot(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """Slot 1 is free because the device only knows 0 and 2."""
    document = load_json("foody_timers.json")
    template = document["schedules"][0]
    document["schedules"] = [
        {**template, "schedule_id": 0},
        {**template, "schedule_id": 2},
    ]
    mock_foody.get_timers.return_value = FoodyTimers.from_dict(document)
    await call(
        hass,
        SERVICE_ADD_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "time": "07:00:00", "portions": 1},
    )
    assert mock_foody.set_schedule.await_args.args[0].schedule_id == 1


async def test_add_rejects_a_full_device_before_asking_the_firmware(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """All 20 slots taken is a validation error, not a firmware round trip."""
    mock_foody.get_timers.return_value = make_timers(MAX_FEEDING_SCHEDULES)
    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "time": "07:00:00", "portions": 1},
        )
    assert err.value.translation_key == "no_free_schedule_slot"
    mock_foody.set_schedule.assert_not_awaited()


async def test_set_leaves_omitted_fields_unchanged(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    await call(
        hass,
        SERVICE_SET_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "schedule_id": 0, "portions": 5},
    )
    schedule = mock_foody.set_schedule.await_args.args[0]
    assert mock_foody.set_schedule.await_args.kwargs == {"create": False}
    assert schedule.schedule_id == 0
    assert schedule.portions == 5
    # Everything else is what foody_timers.json holds for slot 0.
    assert schedule.execution_time == time(6, 30)
    assert schedule.weekdays == frozenset(range(7))
    assert schedule.enabled is True
    assert schedule.skip_once is False
    assert schedule.fresh_food_mode is False
    assert schedule.auto_play_voice is True


async def test_set_rereads_before_writing(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """The freshly read schedule is the base of the change, never the cached one."""
    document = load_json("foody_timers.json")
    document["schedules"][0]["portions"] = 9
    mock_foody.get_timers.return_value = FoodyTimers.from_dict(document)
    mock_foody.reset_mock()
    await call(
        hass,
        SERVICE_SET_FEEDING_SCHEDULE,
        {"device_id": foody_device_id, "schedule_id": 0, "enabled": False},
    )
    assert [name for name, *_ in mock_foody.mock_calls][:2] == ["get_timers", "set_schedule"]
    schedule = mock_foody.set_schedule.await_args.args[0]
    assert schedule.portions == 9
    assert schedule.enabled is False


async def test_set_can_change_every_field(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    await call(
        hass,
        SERVICE_SET_FEEDING_SCHEDULE,
        {
            "device_id": foody_device_id,
            "schedule_id": 0,
            "time": "09:15:00",
            "portions": 3,
            "weekdays": ["sun"],
            "enabled": False,
            "skip_once": True,
            "fresh_food_mode": True,
            "auto_play_voice": False,
        },
    )
    schedule = mock_foody.set_schedule.await_args.args[0]
    assert schedule.execution_time == time(9, 15)
    assert schedule.portions == 3
    assert schedule.weekdays == frozenset({0})
    assert schedule.enabled is False
    assert schedule.skip_once is True
    assert schedule.fresh_food_mode is True
    assert schedule.auto_play_voice is False


async def test_a_write_marks_the_timers_stale_and_refreshes(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    with (
        patch.object(KlyqaDeviceCoordinator, "mark_timers_stale") as mark_stale,
        patch.object(
            KlyqaDeviceCoordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
    ):
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )
    assert mark_stale.call_count == 1
    assert refresh.await_count == 1


async def test_a_failed_write_marks_the_cache_stale(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """The firmware clears its own slot before it tells the MCU, so a rejected delete
    may still have removed the schedule. The cached document can no longer be trusted."""
    mock_foody.delete_schedule.side_effect = KlyqaDeviceError(["nope"])
    with (
        patch.object(KlyqaDeviceCoordinator, "mark_timers_stale") as mark_stale,
        pytest.raises(HomeAssistantError),
    ):
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )
    assert mark_stale.call_count == 1


async def test_a_failed_write_does_not_force_a_refresh(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """Re-reading is left to the next scheduled poll; the device just refused a request."""
    mock_foody.delete_schedule.side_effect = KlyqaDeviceError(["nope"])
    with (
        patch.object(
            KlyqaDeviceCoordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
        pytest.raises(HomeAssistantError),
    ):
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )
    refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [KlyqaAuthError("bad token"), KlyqaConnectionError("unreachable")]
)
async def test_every_library_error_reaches_the_user_translated(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str, error: Exception
) -> None:
    mock_foody.get_timers.side_effect = error
    with pytest.raises(HomeAssistantError, match="Feeder"):
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )


async def test_a_failing_read_is_reported(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """The re-read is a device round trip of its own and can fail too."""
    mock_foody.get_timers.side_effect = KlyqaDeviceError(["timer busy"])
    with pytest.raises(HomeAssistantError, match="timer busy"):
        await call(
            hass,
            SERVICE_DELETE_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "schedule_id": 0},
        )


@pytest.mark.parametrize(
    ("service", "data"),
    [
        (SERVICE_ADD_FEEDING_SCHEDULE, {"time": "07:00:00", "portions": 0}),
        (SERVICE_ADD_FEEDING_SCHEDULE, {"time": "07:00:00", "portions": 41}),
        (SERVICE_ADD_FEEDING_SCHEDULE, {"time": "07:00:00", "portions": 1, "weekdays": []}),
        (
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"time": "07:00:00", "portions": 1, "weekdays": ["someday"]},
        ),
        (SERVICE_SET_FEEDING_SCHEDULE, {"schedule_id": -1, "portions": 1}),
        (SERVICE_SET_FEEDING_SCHEDULE, {"schedule_id": MAX_FEEDING_SCHEDULES, "portions": 1}),
    ],
)
async def test_the_schema_rejects_impossible_values(
    hass: HomeAssistant, foody_device_id: str, service: str, data: dict[str, Any]
) -> None:
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await call(hass, service, {"device_id": foody_device_id, **data})


async def test_the_services_exist_without_a_config_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    """Registered in async_setup, so neither setting up nor unloading an entry moves them."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    for service in (
        SERVICE_ADD_FEEDING_SCHEDULE,
        SERVICE_SET_FEEDING_SCHEDULE,
        SERVICE_DELETE_FEEDING_SCHEDULE,
    ):
        assert hass.services.has_service(DOMAIN, service)

    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    for service in (
        SERVICE_ADD_FEEDING_SCHEDULE,
        SERVICE_SET_FEEDING_SCHEDULE,
        SERVICE_DELETE_FEEDING_SCHEDULE,
    ):
        assert hass.services.has_service(DOMAIN, service)


async def test_two_parallel_adds_claim_different_slots(
    hass: HomeAssistant, mock_foody: MagicMock, foody_device_id: str
) -> None:
    """Read and write are one sequence: the second add must see the first one's slot taken.

    The device mock keeps the schedule list it is given and yields at every await, so an
    implementation that does not hold the coordinator's write lock across read and write
    lets both calls read the same list and claim the same free slot.
    """
    document = load_json("foody_timers.json")
    schedules = list(document["schedules"])

    async def _get_timers() -> FoodyTimers:
        await asyncio.sleep(0)
        return FoodyTimers.from_dict({**document, "schedules": list(schedules)})

    async def _set_schedule(schedule: Any, *, create: bool) -> FoodyTimers:
        await asyncio.sleep(0)
        schedules.append(schedule.to_dict())
        return FoodyTimers.from_dict({**document, "schedules": list(schedules)})

    mock_foody.get_timers.side_effect = _get_timers
    mock_foody.set_schedule.side_effect = _set_schedule

    await asyncio.gather(
        call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "time": "07:00:00", "portions": 1},
        ),
        call(
            hass,
            SERVICE_ADD_FEEDING_SCHEDULE,
            {"device_id": foody_device_id, "time": "18:00:00", "portions": 2},
        ),
    )
    claimed = sorted(
        written.args[0].schedule_id for written in mock_foody.set_schedule.await_args_list
    )
    # Slot 0 comes from foody_timers.json, so the two adds take 1 and 2.
    assert claimed == [1, 2]


COMPONENT = Path(__file__).parent.parent / "custom_components" / "klyqa_pet"


def json_keys(value: Any, path: str = "") -> set[str]:
    if isinstance(value, dict):
        return {key for name, item in value.items() for key in json_keys(item, f"{path}/{name}")}
    return {path}


def test_the_translation_files_stay_in_key_parity() -> None:
    reference = json_keys(json.loads((COMPONENT / "strings.json").read_text()))
    for name in ("en", "de"):
        translation = json_keys(
            json.loads((COMPONENT / "translations" / f"{name}.json").read_text())
        )
        assert translation == reference, name


def test_services_yaml_matches_the_schemas_and_the_strings(
    hass: HomeAssistant, integration: None
) -> None:
    """Every action is described, and every described field exists in its schema."""
    described = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]
    icons = json.loads((COMPONENT / "icons.json").read_text())["services"]
    registered = {
        SERVICE_ADD_FEEDING_SCHEDULE: ADD_SCHEMA,
        SERVICE_SET_FEEDING_SCHEDULE: SET_SCHEMA,
        SERVICE_DELETE_FEEDING_SCHEDULE: DELETE_SCHEMA,
    }
    assert set(described) == set(registered) == set(strings) == set(icons)
    assert set(hass.services.async_services_for_domain(DOMAIN)) == set(registered)
    for name, schema in registered.items():
        fields = set(described[name]["fields"])
        assert fields == {str(key) for key in schema.schema}, name
        assert set(strings[name]["fields"]) == fields, name
    # The numeric bounds are duplicated in YAML; keep them tied to the library's limits.
    for name in (SERVICE_ADD_FEEDING_SCHEDULE, SERVICE_SET_FEEDING_SCHEDULE):
        portions = described[name]["fields"]["portions"]["selector"]["number"]
        assert (portions["min"], portions["max"]) == (1, MAX_PORTIONS), name
    for name in (SERVICE_SET_FEEDING_SCHEDULE, SERVICE_DELETE_FEEDING_SCHEDULE):
        schedule_id = described[name]["fields"]["schedule_id"]["selector"]["number"]
        assert (schedule_id["min"], schedule_id["max"]) == (0, MAX_FEEDING_SCHEDULES - 1), name
    for name in (SERVICE_ADD_FEEDING_SCHEDULE, SERVICE_SET_FEEDING_SCHEDULE):
        duration = described[name]["fields"]["duration"]["selector"]["number"]
        assert (duration["min"], duration["max"]) == (0, MAX_DURATION_SEC), name


def test_the_weekday_selector_offers_exactly_the_known_keys() -> None:
    described = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    options = described[SERVICE_ADD_FEEDING_SCHEDULE]["fields"]["weekdays"]["selector"]["select"]
    assert tuple(options["options"]) == WEEKDAY_KEYS
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        translations = json.loads((COMPONENT / name).read_text())
        assert tuple(translations["selector"]["weekdays"]["options"]) == WEEKDAY_KEYS, name
