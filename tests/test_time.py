"""Tests for the time platform."""

from datetime import time
from unittest.mock import MagicMock, patch

from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import setup_integration


@pytest.fixture
async def times(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.TIME]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "times")
async def test_times(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("times")
async def test_setting_the_sleep_start_preserves_the_end(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Setting sleep_start must not disturb end, weekdays or the enabled flag."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_start", "time": "21:30:00"},
        blocking=True,
    )
    sent = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent.start == time(21, 30)
    assert sent.end == time(6, 0)
    assert sent.enabled is False
    assert sent.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("times")
async def test_setting_the_sleep_end_preserves_the_start(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Setting sleep_end must not disturb start, weekdays or the enabled flag."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_end", "time": "07:15:00"},
        blocking=True,
    )
    sent = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent.end == time(7, 15)
    assert sent.start == time(22, 0)
    assert sent.enabled is False
    assert sent.weekdays == frozenset(range(7))
