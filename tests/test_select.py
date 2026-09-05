"""Tests for the select platform."""

from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.select import ATTR_OPTION, DOMAIN as SELECT_DOMAIN, SERVICE_SELECT_OPTION
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import setup_integration


@pytest.fixture
async def selects(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_cloud: MagicMock, mock_devices: dict
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SELECT]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "selects")
async def test_selects(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("selects")
async def test_select_commands(hass: HomeAssistant, mock_welly: MagicMock, mock_foody: MagicMock) -> None:
    assert hass.states.get("select.kitchen_fountain_mode").state == "fresh_water_24h"
    await hass.services.async_call(
        SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.kitchen_fountain_mode", ATTR_OPTION: "water_change"}, blocking=True,
    )
    mock_welly.set_mode.assert_awaited_with(2)
    await hass.services.async_call(
        SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.feeder_custom_button_function", ATTR_OPTION: "privacy_mode"}, blocking=True,
    )
    mock_foody.update_settings.assert_awaited_with(custom_button_function=3)
    await hass.services.async_call(
        SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.feeder_charging_protection", ATTR_OPTION: "continue_charging"}, blocking=True,
    )
    mock_foody.update_settings.assert_awaited_with(charging_protection=2)
