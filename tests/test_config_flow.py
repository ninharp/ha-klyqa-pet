"""Tests for the config flow."""

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.klyqa_pet.const import (
    CONF_DEVICES,
    CONF_ENVIRONMENT,
    CONF_MANUAL_DEVICES,
    DOMAIN,
)
from pyklyqa_pet import KlyqaAuthError, KlyqaConnectionError

from .conftest import WELLY_HOST, WELLY_ID, device_record, setup_integration

USER_INPUT = {CONF_ENVIRONMENT: "test", CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
CLOUD_DEVICES = {
    WELLY_ID: device_record("welly-token", "Kitchen fountain", "@klyqa.welly-dev", None)
}


def zeroconf_info(
    device_id: str = WELLY_ID, product_id: str = "@klyqa.welly-dev"
) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(WELLY_HOST),
        ip_addresses=[ip_address(WELLY_HOST)],
        hostname="KLYQA-AF2D7C.local.",
        name=f"{product_id[1:]}-{device_id}._qcxrest._tcp.local.",
        port=3333,
        properties={
            "productId": product_id,
            "localDeviceId": device_id,
            "productName": "Klyqa Welly",
            "deviceName": "Kitchen fountain",
            "state": "NA",
            "path": "/api/v1/",
        },
        type="_qcxrest._tcp.local.",
    )


@pytest.fixture
def mock_fetch() -> Any:
    with patch(
        "custom_components.klyqa_pet.config_flow.async_fetch_cloud_devices",
        new=AsyncMock(return_value=CLOUD_DEVICES),
    ) as fetch:
        yield fetch


@pytest.fixture
def mock_setup_entry() -> Any:
    with patch("custom_components.klyqa_pet.async_setup_entry", return_value=True) as setup:
        yield setup


async def test_user_flow_success(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com (test)"
    assert result["data"] == {**USER_INPUT, CONF_DEVICES: CLOUD_DEVICES}
    assert result["result"].unique_id == "test:user@example.com"
    mock_fetch.assert_awaited_once_with(hass, "test", "user@example.com", "secret")
    mock_setup_entry.assert_called_once()


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (KlyqaAuthError("bad"), "invalid_auth"),
        (KlyqaConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    mock_fetch: AsyncMock,
    mock_setup_entry: Any,
    side_effect: Exception,
    error: str,
) -> None:
    mock_fetch.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_fetch.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_account(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_fetch: AsyncMock
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_unsupported_product(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info("80659988019C", "@klyqa.lighting.kl-rgbc3.rgbcw"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_zeroconf_known_device_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_known_manual_device_aborts(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com (test)",
        unique_id="test:user@example.com",
        data={CONF_ENVIRONMENT: "test", CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        options={
            CONF_MANUAL_DEVICES: {
                WELLY_ID: device_record("welly-token", "", "@klyqa.welly-dev", WELLY_HOST)
            }
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_new_device_leads_to_login(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"]["host"] == WELLY_HOST

    # a second announcement of the same device must not open a second flow
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_in_progress"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "test:user@example.com"


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_fetch: AsyncMock,
    mock_cloud: Any,
    mock_devices: dict,
) -> None:
    # start with a stale token so the assertion below proves a fresh one was fetched
    mock_config_entry.data[CONF_DEVICES][WELLY_ID]["access_token"] = "old-token"
    await setup_integration(hass, mock_config_entry)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    mock_fetch.side_effect = KlyqaAuthError("bad")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_fetch.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-secret"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-secret"
    # stored host survives the token refresh
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == WELLY_HOST
    # the fresh access token from the cloud landed in the stored device record
    assert (
        mock_config_entry.data[CONF_DEVICES][WELLY_ID]["access_token"]
        == CLOUD_DEVICES[WELLY_ID]["access_token"]
    )


async def test_reconfigure_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_fetch: AsyncMock,
    mock_cloud: Any,
    mock_devices: dict,
) -> None:
    original_title = mock_config_entry.title
    await setup_integration(hass, mock_config_entry)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "changed"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "changed"
    assert mock_config_entry.title == original_title
    # stored host survives the merge
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == WELLY_HOST
