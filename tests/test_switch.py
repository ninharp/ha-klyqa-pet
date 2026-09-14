"""Tests for the switch platform."""

from datetime import time
from unittest.mock import MagicMock, patch

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from pyklyqa_pet import KlyqaDeviceError

from .conftest import setup_integration


@pytest.fixture
async def switches(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SWITCH]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "switches")
async def test_switches(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("switches")
@pytest.mark.parametrize(
    ("entity_id", "device", "method", "on_kwargs", "off_kwargs"),
    [
        (
            "switch.kitchen_fountain_heating",
            "mock_welly",
            "set_heating",
            {"enabled": True},
            {"enabled": False},
        ),
        (
            "switch.kitchen_fountain_light",
            "mock_welly",
            "update_settings",
            {"light_switch": True},
            {"light_switch": False},
        ),
        (
            "switch.feeder_pet_lock",
            "mock_foody",
            "update_settings",
            {"app_pet_lock": True},
            {"app_pet_lock": False},
        ),
        (
            "switch.klyqa_airpurifier_e85dfc_ionizer",
            "mock_purifier",
            "set_ionizer",
            {"on": True},
            {"on": False},
        ),
        (
            "switch.klyqa_airpurifier_e85dfc_child_lock",
            "mock_purifier",
            "set_child_lock",
            {"on": True},
            {"on": False},
        ),
    ],
)
async def test_switch_commands(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    entity_id: str,
    device: str,
    method: str,
    on_kwargs: dict,
    off_kwargs: dict,
) -> None:
    mock = request.getfixturevalue(device)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    getattr(mock, method).assert_awaited_with(**on_kwargs)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    getattr(mock, method).assert_awaited_with(**off_kwargs)


@pytest.mark.usefixtures("switches")
async def test_sleep_mode_switch_writes_the_whole_object(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Toggling preserves weekdays and times; only `enabled` changes."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.feeder_sleep_mode"},
        blocking=True,
    )
    sent = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent.enabled is True
    assert sent.start == time(22, 0)
    assert sent.end == time(6, 0)
    assert sent.weekdays == frozenset(range(7))

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.feeder_sleep_mode"},
        blocking=True,
    )
    sent_off = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent_off.enabled is False
    assert sent_off.start == time(22, 0)
    assert sent_off.end == time(6, 0)
    assert sent_off.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("switches")
async def test_quiet_time_switch_preserves_other_fields(
    hass: HomeAssistant, mock_welly: MagicMock
) -> None:
    """Toggling `quiet_time` must leave start, end and the water flag untouched."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.kitchen_fountain_quiet_time"},
        blocking=True,
    )
    sent = mock_welly.set_quiet_time.await_args.args[0]
    assert sent.enabled is True
    assert sent.start == time(22, 0)
    assert sent.end == time(7, 0)
    assert sent.water_enabled is False
    assert sent.weekdays == frozenset(range(7))

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.kitchen_fountain_quiet_time"},
        blocking=True,
    )
    sent_off = mock_welly.set_quiet_time.await_args.args[0]
    assert sent_off.enabled is False
    assert sent_off.start == time(22, 0)
    assert sent_off.end == time(7, 0)
    assert sent_off.water_enabled is False
    assert sent_off.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("switches")
async def test_quiet_time_water_switch_preserves_other_fields(
    hass: HomeAssistant, mock_welly: MagicMock
) -> None:
    """Toggling `quiet_time_water` must leave enabled, start, end and weekdays untouched."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.kitchen_fountain_quiet_time_water"},
        blocking=True,
    )
    sent = mock_welly.set_quiet_time.await_args.args[0]
    assert sent.water_enabled is True
    assert sent.enabled is False
    assert sent.start == time(22, 0)
    assert sent.end == time(7, 0)
    assert sent.weekdays == frozenset(range(7))

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.kitchen_fountain_quiet_time_water"},
        blocking=True,
    )
    sent_off = mock_welly.set_quiet_time.await_args.args[0]
    assert sent_off.water_enabled is False
    assert sent_off.enabled is False
    assert sent_off.start == time(22, 0)
    assert sent_off.end == time(7, 0)
    assert sent_off.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("switches")
async def test_switch_command_error(hass: HomeAssistant, mock_welly: MagicMock) -> None:
    mock_welly.set_heating.side_effect = KlyqaDeviceError(["Invalid heating value"])
    with pytest.raises(HomeAssistantError, match="rejected the command"):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.kitchen_fountain_heating"},
            blocking=True,
        )
