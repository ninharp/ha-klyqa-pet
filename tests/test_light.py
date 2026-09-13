"""Tests for the light platform (air purifier LED and Strype strip)."""

from unittest.mock import MagicMock, patch

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import setup_integration

ENTITY_ID = "light.klyqa_airpurifier_e85dfc_led"


@pytest.fixture
async def lights(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "lights")
async def test_light(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)
    state = hass.states.get(ENTITY_ID)
    assert state.state == "on"
    assert state.attributes[ATTR_RGB_COLOR] == (160, 40, 240)
    assert state.attributes[ATTR_BRIGHTNESS] == 204


@pytest.mark.usefixtures("lights")
async def test_light_commands(hass: HomeAssistant, mock_purifier: MagicMock) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_RGB_COLOR: (1, 2, 3)},
        blocking=True,
    )
    mock_purifier.set_led.assert_awaited_with(True, (1, 2, 3), None)
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    mock_purifier.set_led.assert_awaited_with(True, None, 50)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    mock_purifier.set_led.assert_awaited_with(True, None, None)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    mock_purifier.set_led.assert_awaited_with(False)


@pytest.mark.usefixtures("lights")
async def test_strype_light_reports_rgb_mode(hass: HomeAssistant) -> None:
    state = hass.states.get("light.living_room_strip_strip")
    assert state.state == "on"
    assert state.attributes["color_mode"] == ColorMode.RGB
    assert state.attributes["rgb_color"] == (255, 128, 0)
    assert state.attributes["brightness"] == 178  # round(70 * 255 / 100) == round(178.5) == 178


@pytest.mark.usefixtures("lights")
async def test_strype_light_sets_colour_temperature(
    hass: HomeAssistant, mock_strype: MagicMock
) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": "light.living_room_strip_strip", "color_temp_kelvin": 3000},
        blocking=True,
    )
    mock_strype.set_state.assert_awaited_with(
        power_on=True,
        rgb=None,
        temperature_kelvin=3000,
        brightness_percent=None,
        transition_ms=None,
    )


@pytest.mark.usefixtures("lights")
async def test_strype_light_turn_off_with_transition(
    hass: HomeAssistant, mock_strype: MagicMock
) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {"entity_id": "light.living_room_strip_strip", "transition": 2},
        blocking=True,
    )
    mock_strype.set_state.assert_awaited_with(power_on=False, transition_ms=2000)
