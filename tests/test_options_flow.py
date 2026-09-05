"""Tests for the manual-device options flow."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.klyqa_pet.const import CONF_MANUAL_DEVICES
from pyklyqa_pet import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

from .conftest import WELLY_ID, make_system_info, setup_integration

MANUAL_INPUT = {"host": "192.168.2.99", "port": 3333, "access_token": "aabbccddeeff0011223344"}


@pytest.fixture
def mock_manual_device() -> Any:
    with patch("custom_components.klyqa_pet.config_flow.KlyqaDevice", autospec=True) as cls:
        cls.return_value.get_system_info = AsyncMock(
            return_value=make_system_info("@klyqa.welly-dev", "AABBCCDDEE01", "Klyqa Welly")
        )
        yield cls.return_value


async def test_add_manual_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_manual_device: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(result["flow_id"], MANUAL_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    manual = mock_config_entry.options[CONF_MANUAL_DEVICES]
    assert manual["AABBCCDDEE01"]["host"] == "192.168.2.99"
    assert manual["AABBCCDDEE01"]["product_id"] == "@klyqa.welly-dev"
    # entry was reloaded and the manual device got a coordinator
    assert "AABBCCDDEE01" in mock_config_entry.runtime_data.coordinators
    assert mock_config_entry.runtime_data.coordinators["AABBCCDDEE01"].is_manual is True


async def test_add_manual_device_releases_it_from_owning_account_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_local_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_manual_device: MagicMock,
) -> None:
    """Claiming a device via the options flow must release it from the account entry.

    A device is owned by exactly one config entry: adding it manually to a local
    entry that already has an options flow open must schedule a reload of any
    other loaded entry that still lists it as a cloud record.
    """
    await setup_integration(hass, mock_config_entry)
    mock_local_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_local_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_manual_device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.welly-dev", WELLY_ID, "Klyqa Welly")
    )
    result = await hass.config_entries.options.async_init(mock_local_config_entry.entry_id)
    with patch.object(hass.config_entries, "async_schedule_reload") as mock_reload:
        result = await hass.config_entries.options.async_configure(result["flow_id"], MANUAL_INPUT)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_reload.assert_any_call(mock_config_entry.entry_id)


@pytest.mark.parametrize(
    ("side_effect", "product_id", "error"),
    [
        (KlyqaAuthError("401"), "@klyqa.welly-dev", "invalid_auth"),
        (KlyqaConnectionError("down"), "@klyqa.welly-dev", "cannot_connect"),
        (KlyqaDeviceError("error body"), "@klyqa.welly-dev", "cannot_connect"),
        (RuntimeError("boom"), "@klyqa.welly-dev", "unknown"),
        (None, "@klyqa.lighting.kl-rgbc3.rgbcw", "not_supported"),
    ],
)
async def test_add_manual_device_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_manual_device: MagicMock,
    side_effect: Exception | None,
    product_id: str,
    error: str,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_manual_device.get_system_info.side_effect = side_effect
    mock_manual_device.get_system_info.return_value = make_system_info(
        product_id, "AABBCCDDEE01", "x"
    )
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], MANUAL_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
