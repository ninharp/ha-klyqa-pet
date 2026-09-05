"""Tests for the button platform."""

from unittest.mock import MagicMock, patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import FOODY_ID, setup_integration


@pytest.fixture
async def buttons(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.BUTTON]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "buttons")
async def test_buttons(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "buttons")
async def test_button_presses(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_welly: MagicMock,
    mock_foody: MagicMock,
    mock_purifier: MagicMock,
) -> None:
    async def press(entity_id: str) -> None:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

    await press("button.kitchen_fountain_start_descaling")
    mock_welly.set_descaling.assert_awaited_with(True)
    await press("button.kitchen_fountain_stop_descaling")
    mock_welly.set_descaling.assert_awaited_with(False)

    mock_config_entry.runtime_data.coordinators[FOODY_ID].dispense_portions = 4
    await press("button.feeder_dispense_food")
    mock_foody.dispense.assert_awaited_with(4)
    await press("button.feeder_play_voice_recording")
    mock_foody.play_voice_recording.assert_awaited_once()
    await press("button.feeder_query_bowl_weight")
    mock_foody.query_realtime_weight.assert_awaited_once()

    await press("button.klyqa_airpurifier_e85dfc_restart")
    mock_purifier.reboot.assert_awaited_once()
    mock_purifier.request.assert_not_called()
