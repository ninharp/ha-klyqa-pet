"""Tests for the config flow."""

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_PORT
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
    ENVIRONMENT_LOCAL,
    LOCAL_ENTRY_UNIQUE_ID,
)
from pyklyqa_pet import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

from .conftest import (
    FOODY_ID,
    MANUAL_HOST,
    MANUAL_ID,
    WELLY_HOST,
    WELLY_ID,
    device_record,
    make_system_info,
    setup_integration,
)

USER_INPUT = {CONF_ENVIRONMENT: "test", CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
CLOUD_DEVICES = {
    WELLY_ID: device_record("welly-token", "Kitchen fountain", "@klyqa.welly-dev", None)
}
LOCAL_INPUT = {"host": MANUAL_HOST, "port": 3333, "access_token": "aabbccddeeff0011223344"}


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


@pytest.fixture
def mock_manual_device() -> Any:
    with patch("custom_components.klyqa_pet.config_flow.KlyqaDevice", autospec=True) as cls:
        cls.return_value.get_system_info = AsyncMock(
            return_value=make_system_info("@klyqa.welly-dev", MANUAL_ID, "Klyqa Welly")
        )
        yield cls.return_value


async def test_user_flow_shows_menu(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert result["menu_options"] == ["cloud", "local"]


async def test_user_flow_success(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cloud"

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
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
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
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_local_flow_creates_entry(
    hass: HomeAssistant, mock_manual_device: Any, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Klyqa Pet (local)"
    assert result["data"] == {CONF_ENVIRONMENT: ENVIRONMENT_LOCAL, CONF_DEVICES: {}}
    manual = result["options"][CONF_MANUAL_DEVICES]
    assert manual[MANUAL_ID]["host"] == MANUAL_HOST
    assert manual[MANUAL_ID]["access_token"] == LOCAL_INPUT["access_token"]
    assert manual[MANUAL_ID]["product_id"] == "@klyqa.welly-dev"
    assert result["result"].unique_id == LOCAL_ENTRY_UNIQUE_ID
    mock_setup_entry.assert_called_once()


async def test_local_flow_create_releases_device_from_owning_account_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: Any,
    mock_devices: dict,
    mock_manual_device: Any,
) -> None:
    """Creating a new local entry for a device already owned by an account entry.

    A device is owned by exactly one config entry: manually adding it here must
    schedule a reload of the loaded account entry that still lists it as a cloud
    record, so that entry gives it up.
    """
    await setup_integration(hass, mock_config_entry)
    mock_manual_device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.welly-dev", WELLY_ID, "Klyqa Welly")
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    with patch.object(hass.config_entries, "async_schedule_reload") as mock_reload:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_reload.assert_any_call(mock_config_entry.entry_id)


async def test_local_flow_second_device_added_to_existing_entry(
    hass: HomeAssistant,
    mock_local_config_entry: MockConfigEntry,
    mock_devices: dict,
    mock_manual_device: Any,
) -> None:
    mock_local_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_local_config_entry.entry_id)
    await hass.async_block_till_done()

    second_id = "AABBCCDDEE02"
    mock_manual_device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.foody-dev", second_id, "Klyqa Foody")
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.2.100", "port": 3333, "access_token": "tok2"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "device_added"

    manual = mock_local_config_entry.options[CONF_MANUAL_DEVICES]
    assert set(manual) == {MANUAL_ID, second_id}
    assert set(mock_local_config_entry.runtime_data.coordinators) == {MANUAL_ID, second_id}


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
async def test_local_flow_errors(
    hass: HomeAssistant,
    mock_manual_device: Any,
    side_effect: Exception | None,
    product_id: str,
    error: str,
) -> None:
    mock_manual_device.get_system_info.side_effect = side_effect
    mock_manual_device.get_system_info.return_value = make_system_info(product_id, MANUAL_ID, "x")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


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


async def test_zeroconf_discovery_confirm_shows_menu(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "discovery_confirm"
    assert result["menu_options"] == ["cloud", "local"]
    assert result["description_placeholders"] == {
        "name": "Kitchen fountain",
        "host": WELLY_HOST,
        "product": "Klyqa Welly",
    }
    flows = hass.config_entries.flow.async_progress(DOMAIN)
    assert flows[0]["context"]["title_placeholders"] == {
        "product": "Klyqa Welly",
        "name": "Kitchen fountain",
    }

    # a second announcement of the same device must not open a second flow
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_in_progress"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cloud"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "test:user@example.com"


async def test_zeroconf_discovery_local_prefills_host(
    hass: HomeAssistant, mock_manual_device: Any, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local"
    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if getattr(key, "description", None)
    }
    assert suggested[CONF_HOST] == WELLY_HOST
    assert suggested[CONF_PORT] == 3333

    # the user only has to type the token; host/port come from the suggested values
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": WELLY_HOST, "port": 3333, "access_token": "aabbccddeeff0011223344"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_zeroconf_new_device_leads_to_login(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=zeroconf_info()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"}
    )
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
    await setup_integration(hass, mock_config_entry)
    # Stamp a stale token onto the already-loaded entry, after setup ran its own token
    # refresh, so the assertion below proves reauth (not setup) is what fetches the
    # fresh token.
    data = mock_config_entry.data
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **data,
            CONF_DEVICES: {
                **data[CONF_DEVICES],
                WELLY_ID: {**data[CONF_DEVICES][WELLY_ID], "access_token": "old-token"},
            },
        },
    )
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


async def test_reconfigure_local_entry_aborts(
    hass: HomeAssistant, mock_local_config_entry: MockConfigEntry
) -> None:
    mock_local_config_entry.add_to_hass(hass)
    result = await mock_local_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported_local"


async def test_completing_cloud_flow_aborts_other_discovery_flows(
    hass: HomeAssistant, mock_fetch: AsyncMock, mock_setup_entry: Any
) -> None:
    """Adopting an account must clean up every other device's stale discovery card."""
    result1 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info(WELLY_ID, "@klyqa.welly-dev"),
    )
    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info(FOODY_ID, "@klyqa.foody-dev"),
    )
    assert result1["type"] is FlowResultType.MENU
    assert result2["type"] is FlowResultType.MENU

    mock_fetch.return_value = {
        WELLY_ID: device_record("welly-token", "Kitchen fountain", "@klyqa.welly-dev", None),
        FOODY_ID: device_record("foody-token", "Feeder", "@klyqa.foody-dev", None),
    }
    result1 = await hass.config_entries.flow.async_configure(
        result1["flow_id"], {"next_step_id": "cloud"}
    )
    result1 = await hass.config_entries.flow.async_configure(result1["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result1["type"] is FlowResultType.CREATE_ENTRY

    assert hass.config_entries.flow.async_progress(DOMAIN) == []


async def test_completing_local_flow_aborts_matching_discovery_flow(
    hass: HomeAssistant, mock_manual_device: Any, mock_setup_entry: Any
) -> None:
    """Adding a device manually must only abort that device's own discovery card."""
    flow_a = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info(WELLY_ID, "@klyqa.welly-dev"),
    )
    flow_b = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info(FOODY_ID, "@klyqa.foody-dev"),
    )
    assert flow_a["type"] is FlowResultType.MENU
    assert flow_b["type"] is FlowResultType.MENU

    mock_manual_device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.welly-dev", WELLY_ID, "Klyqa Welly")
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    remaining = hass.config_entries.flow.async_progress(DOMAIN)
    assert [flow["flow_id"] for flow in remaining] == [flow_b["flow_id"]]


async def test_discovery_confirm_aborts_when_meanwhile_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A discovery card must not show its menu again once the device got configured."""
    mock_config_entry.add_to_hass(hass)
    new_id = "AABBCCDDEE99"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=zeroconf_info(new_id, "@klyqa.welly-dev"),
    )
    assert result["type"] is FlowResultType.MENU

    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_DEVICES: {
                **mock_config_entry.data[CONF_DEVICES],
                new_id: device_record("new-token", "New device", "@klyqa.welly-dev", WELLY_HOST),
            },
        },
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"], None)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
