"""Tests for translated UpdateFailed messages raised by the coordinator."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.klyqa_pet.const import SCAN_INTERVAL
from pyklyqa_pet import KlyqaConnectionError

from .conftest import WELLY_ID, setup_integration


async def test_update_failed_message_is_rendered(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """The UpdateFailed raised for a plain connection error must render, not stay a bare key.

    Regression test for a startup race: on a real HA instance, the very first coordinator
    refresh (triggered synchronously while the config entry is being set up) could run
    before this integration's own "exceptions" translations were cached, so the log showed
    the literal translation key ("update_failed") instead of the rendered message. See
    custom_components/klyqa_pet/__init__.py:async_setup_entry, which now loads this
    integration's translations up front to close that race.
    """
    await setup_integration(hass, mock_config_entry)
    mock_welly.get_state.side_effect = KlyqaConnectionError("device answered HTTP 500")
    # A coordinator only polls while an entity listens to it.
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.last_update_success is False
    message = str(coordinator.last_exception)
    assert message != "update_failed"
    assert coordinator.device_name in message
    assert "device answered HTTP 500" in message
