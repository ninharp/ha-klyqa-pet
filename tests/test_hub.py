"""Tests for discovery handling and token recovery in the hub."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from zeroconf import ServiceStateChange

from custom_components.klyqa_pet.const import (
    CONF_DEVICES,
    CONF_MANUAL_DEVICES,
    DOMAIN,
    SCAN_INTERVAL,
    SYSTEM_INFO_INTERVAL,
)
from pyklyqa_pet import (
    CloudDevice,
    DeviceType,
    DiscoveredDevice,
    KlyqaAuthError,
    KlyqaConnectionError,
)

from .conftest import FOODY_ID, PURIFIER_ID, WELLY_HOST, WELLY_ID, device_record, setup_integration

MANUAL_ID = "AABBCCDDEE01"


def _discovered(
    device_id: str, host: str, product_id: str = "@klyqa.welly-dev"
) -> DiscoveredDevice:
    return DiscoveredDevice(
        host=host,
        port=3333,
        product_id=product_id,
        local_device_id=device_id,
        product_name="Klyqa Welly",
        device_name="Kitchen fountain",
        device_type=DeviceType.WELLY,
    )


async def test_discovery_adds_device_without_stored_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    mock_config_entry.add_to_hass(hass)
    devices = {
        k: {kk: vv for kk, vv in v.items() if kk not in ("host", "port")}
        for k, v in mock_config_entry.data[CONF_DEVICES].items()
    }
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_DEVICES: devices}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    hub = mock_config_entry.runtime_data
    assert hub.coordinators == {}

    added: list[str] = []
    hub.async_add_new_device_listener(lambda coordinator: added.append(coordinator.local_device_id))
    await hub.async_device_discovered(_discovered(WELLY_ID, WELLY_HOST))
    await hass.async_block_till_done()

    assert added == [WELLY_ID]
    assert WELLY_ID in hub.coordinators
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == WELLY_HOST
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["product_name"] == "Klyqa Welly"


async def test_discovery_ignores_unknown_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    await setup_integration(hass, mock_config_entry)
    hub = mock_config_entry.runtime_data
    await hub.async_device_discovered(_discovered("000000000000", "10.0.0.9"))
    assert "000000000000" not in hub.coordinators


async def test_discovery_updates_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    hub = mock_config_entry.runtime_data
    await hub.async_device_discovered(_discovered(WELLY_ID, "192.168.2.200"))
    await hass.async_block_till_done()
    assert mock_welly.host == "192.168.2.200"
    assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == "192.168.2.200"


async def test_device_401_triggers_token_refresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
    cloud_devices: list[CloudDevice],
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_cloud.login.reset_mock()
    cloud_devices[0] = CloudDevice(
        WELLY_ID, "rotated-token", "Kitchen fountain", "@klyqa.welly-dev", raw={}
    )
    mock_welly.get_state.side_effect = [KlyqaAuthError("401"), mock_welly.get_state.return_value]
    # A coordinator only polls while an entity listens to it.
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_cloud.login.assert_awaited_once()
    assert mock_welly.access_token == "rotated-token"
    assert mock_config_entry.runtime_data.coordinators[WELLY_ID].last_update_success is True


async def test_persistent_401_starts_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_welly.get_state.side_effect = KlyqaAuthError("401")
    # A coordinator only polls while an entity listens to it.
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    flows = hass.config_entries.flow.async_progress(DOMAIN)
    assert flows and flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_stale_device_is_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    cloud_devices: list[CloudDevice],
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    hub = mock_config_entry.runtime_data
    device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, FOODY_ID)}
    )
    del cloud_devices[1]  # Foody disappeared from the account
    await hub.async_refresh_tokens()
    await hass.async_block_till_done()
    assert FOODY_ID not in hub.coordinators
    assert FOODY_ID not in mock_config_entry.data[CONF_DEVICES]
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, FOODY_ID), mock_config_entry.entry_id
        )
        is None
    )


async def test_empty_cloud_list_keeps_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    cloud_devices: list[CloudDevice],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_integration(hass, mock_config_entry)
    hub = mock_config_entry.runtime_data
    cloud_devices.clear()
    await hub.async_refresh_tokens()
    await hass.async_block_till_done()
    assert set(hub.coordinators) == {WELLY_ID, FOODY_ID, PURIFIER_ID}
    assert set(mock_config_entry.data[CONF_DEVICES]) == {WELLY_ID, FOODY_ID, PURIFIER_ID}
    assert "returned no devices" in caplog.text


async def test_manual_device_401_does_not_start_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """A manual device that rejects its token must fail its coordinator, never start reauth."""
    mock_config_entry.add_to_hass(hass)
    # Drop the cloud Welly so the manual device is the only one using mock_welly.
    devices = {k: v for k, v in mock_config_entry.data[CONF_DEVICES].items() if k != WELLY_ID}
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_DEVICES: devices},
        options={
            CONF_MANUAL_DEVICES: {
                MANUAL_ID: device_record(
                    "aabbccddeeff0011223344", "", "@klyqa.welly-dev", "192.168.2.99"
                )
            }
        },
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    hub = mock_config_entry.runtime_data
    mock_cloud.login.reset_mock()

    mock_welly.get_state.side_effect = KlyqaAuthError("401")
    # A coordinator only polls while an entity listens to it.
    hub.coordinators[MANUAL_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hub.coordinators[MANUAL_ID].last_update_success is False
    assert hass.config_entries.flow.async_progress(DOMAIN) == []
    mock_cloud.login.assert_not_awaited()


async def test_401_recovery_cloud_unreachable_fails_update(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_cloud.login.side_effect = KlyqaConnectionError("down")
    mock_welly.get_state.side_effect = KlyqaAuthError("401")
    # A coordinator only polls while an entity listens to it.
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.coordinators[WELLY_ID].last_update_success is False
    assert hass.config_entries.flow.async_progress(DOMAIN) == []
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_system_info_cached_between_polls(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    await setup_integration(hass, mock_config_entry)
    assert mock_welly.get_system_info.await_count == 1
    hub = mock_config_entry.runtime_data
    # A coordinator only polls while an entity listens to it.
    hub.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_welly.get_system_info.await_count == 1

    freezer.tick(SYSTEM_INFO_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_welly.get_system_info.await_count == 2


async def test_service_browser_resolves_and_adds_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_zeroconf_browser: MagicMock,
) -> None:
    mock_config_entry.add_to_hass(hass)
    devices = {
        k: ({kk: vv for kk, vv in v.items() if kk not in ("host", "port")} if k == WELLY_ID else v)
        for k, v in mock_config_entry.data[CONF_DEVICES].items()
    }
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_DEVICES: devices}
    )

    with patch("custom_components.klyqa_pet.hub.AsyncServiceInfo") as mock_info_cls:
        info = mock_info_cls.return_value
        info.async_request = AsyncMock(return_value=True)
        info.parsed_addresses = MagicMock(return_value=["192.168.2.148"])
        info.port = 3333
        info.properties = {
            b"productId": b"@klyqa.welly-dev",
            b"localDeviceId": b"188B0EAF2D7C",
            b"productName": b"Klyqa Welly",
            b"deviceName": b"Kitchen fountain",
        }

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        hub = mock_config_entry.runtime_data
        assert WELLY_ID not in hub.coordinators

        handler = mock_zeroconf_browser.call_args.kwargs["handlers"][0]
        handler(
            zeroconf=MagicMock(),
            service_type="_qcxrest._tcp.local.",
            name="klyqa.welly-dev-188B0EAF2D7C._qcxrest._tcp.local.",
            state_change=ServiceStateChange.Added,
        )
        await hass.async_block_till_done()

        assert WELLY_ID in hub.coordinators
        assert mock_config_entry.data[CONF_DEVICES][WELLY_ID]["host"] == "192.168.2.148"

        before = set(hub.coordinators)
        handler(
            zeroconf=MagicMock(),
            service_type="_qcxrest._tcp.local.",
            name="klyqa.unknown-device-000000000000._qcxrest._tcp.local.",
            state_change=ServiceStateChange.Removed,
        )
        await hass.async_block_till_done()
        assert set(hub.coordinators) == before
