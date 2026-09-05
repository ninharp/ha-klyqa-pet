"""Tests for entry setup and unload."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.klyqa_pet.const import CONF_ACCESS_TOKEN, CONF_DEVICES, DOMAIN
from pyklyqa_pet import CloudDevice, KlyqaAuthError, KlyqaConnectionError

from .conftest import FOODY_ID, PURIFIER_ID, WELLY_ID, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_zeroconf_browser: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    hub = mock_config_entry.runtime_data
    assert set(hub.coordinators) == {WELLY_ID, FOODY_ID, PURIFIER_ID}
    assert hub.coordinators[WELLY_ID].last_update_success is True
    mock_cloud.login.assert_awaited_once_with("user@example.com", "secret")
    mock_zeroconf_browser.assert_called_once()

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_zeroconf_browser.return_value.async_cancel.assert_awaited_once()


async def test_setup_refreshes_tokens(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    cloud_devices: list[CloudDevice],
) -> None:
    cloud_devices[0] = CloudDevice(
        WELLY_ID, "welly-token-2", "Kitchen fountain", "@klyqa.welly-dev", raw={}
    )
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID][CONF_ACCESS_TOKEN] == "welly-token-2"
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == "192.168.2.148"


async def test_setup_cloud_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    mock_cloud.login.side_effect = KlyqaAuthError("bad")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_setup_cloud_unreachable_uses_stored_tokens(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    mock_cloud.login.side_effect = KlyqaConnectionError("down")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(mock_config_entry.runtime_data.coordinators) == 3


async def test_setup_cloud_unreachable_without_devices_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_DEVICES: {}}
    )
    mock_cloud.login.side_effect = KlyqaConnectionError("down")
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_offline_device_does_not_block_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    mock_welly.get_system_info.side_effect = KlyqaConnectionError("timeout")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    hub = mock_config_entry.runtime_data
    assert hub.coordinators[WELLY_ID].last_update_success is False
    assert hub.coordinators[FOODY_ID].last_update_success is True


async def test_platform_forward_failure_shuts_down_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_zeroconf_browser: MagicMock,
) -> None:
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_zeroconf_browser.return_value.async_cancel.assert_awaited_once()
