"""Shared fixtures for the Klyqa Pet integration tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.klyqa_pet.const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_ENVIRONMENT,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    DOMAIN,
)
from pyklyqa_pet import (
    AirPurifierDevice,
    AirPurifierState,
    CloudDevice,
    DeviceType,
    FoodyDevice,
    FoodySettings,
    FoodyState,
    SystemInfo,
    WellyDevice,
    WellySettings,
    WellyState,
)

FIXTURES = Path(__file__).parent / "fixtures"

WELLY_ID = "188B0EAF2D7C"
FOODY_ID = "A0F26219DC34"
PURIFIER_ID = "D83BDAE85DFC"

WELLY_HOST = "192.168.2.148"
FOODY_HOST = "192.168.2.223"
PURIFIER_HOST = "192.168.2.21"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def make_system_info(product_id: str, device_id: str, product_name: str) -> SystemInfo:
    return SystemInfo.from_dict(
        load_json("system_info.json")
        | {"product_id": product_id, "device_id": device_id, "product_name": product_name}
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return the snapshot assertion with the Home Assistant extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def cloud_devices() -> list[CloudDevice]:
    return [
        CloudDevice(WELLY_ID, "welly-token", "Kitchen fountain", "@klyqa.welly-dev", raw={}),
        CloudDevice(FOODY_ID, "foody-token", "Feeder", "@klyqa.foody-dev", raw={}),
        CloudDevice(PURIFIER_ID, "purifier-token", "", "@klyqa.cleaning.airpurifier1", raw={}),
    ]


@pytest.fixture
def mock_cloud(cloud_devices: list[CloudDevice]) -> Generator[MagicMock]:
    """Mock the cloud client used by hub.async_fetch_cloud_devices."""
    with patch("custom_components.klyqa_pet.hub.KlyqaCloudClient", autospec=True) as cls:
        client = cls.return_value
        client.login = AsyncMock(return_value="account-token")
        client.list_devices = AsyncMock(return_value=cloud_devices)
        yield client


@pytest.fixture
def mock_welly() -> MagicMock:
    device = MagicMock(spec=WellyDevice)
    device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.welly-dev", WELLY_ID, "Klyqa Welly")
    )
    device.get_state = AsyncMock(return_value=WellyState.from_dict(load_json("welly_state.json")))
    device.get_settings = AsyncMock(
        return_value=WellySettings.from_dict(load_json("welly_settings.json"))
    )
    return device


@pytest.fixture
def mock_foody() -> MagicMock:
    device = MagicMock(spec=FoodyDevice)
    device.get_system_info = AsyncMock(
        return_value=make_system_info("@klyqa.foody-dev", FOODY_ID, "Klyqa Foody")
    )
    device.get_state = AsyncMock(return_value=FoodyState.from_dict(load_json("foody_state.json")))
    device.get_settings = AsyncMock(
        return_value=FoodySettings.from_dict(load_json("foody_settings.json"))
    )
    return device


@pytest.fixture
def mock_purifier() -> MagicMock:
    device = MagicMock(spec=AirPurifierDevice)
    device.get_system_info = AsyncMock(
        return_value=make_system_info(
            "@klyqa.cleaning.airpurifier1", PURIFIER_ID, "Klyqa airpurifier"
        )
    )
    device.get_state = AsyncMock(
        return_value=AirPurifierState.from_dict(load_json("airpurifier_state.json"))
    )
    return device


@pytest.fixture
def mock_devices(
    mock_welly: MagicMock, mock_foody: MagicMock, mock_purifier: MagicMock
) -> Generator[dict[DeviceType, MagicMock]]:
    """Patch pyklyqa_pet.create_device (as used by the hub) to hand out the mocks."""
    devices = {
        DeviceType.WELLY: mock_welly,
        DeviceType.FOODY: mock_foody,
        DeviceType.AIRPURIFIER: mock_purifier,
    }

    def _create(
        device_type: DeviceType, session: Any, host: str, token: str, port: int = 3333
    ) -> MagicMock:
        device = devices[device_type]
        device.host = host
        device.port = port
        device.access_token = token
        return device

    with patch("custom_components.klyqa_pet.hub.create_device", side_effect=_create):
        yield devices


@pytest.fixture(autouse=True)
def mock_zeroconf_browser(mock_async_zeroconf: MagicMock) -> Generator[MagicMock]:
    """Do not touch real mDNS in tests."""
    with (
        patch(
            "custom_components.klyqa_pet.hub.async_get_async_instance",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("custom_components.klyqa_pet.hub.AsyncServiceBrowser", autospec=True) as browser,
    ):
        browser.return_value.async_cancel = AsyncMock()
        yield browser


def device_record(
    token: str, name: str, product_id: str, host: str | None, product_name: str = ""
) -> dict[str, Any]:
    record: dict[str, Any] = {
        CONF_ACCESS_TOKEN: token,
        CONF_DEVICE_NAME: name,
        CONF_PRODUCT_ID: product_id,
        CONF_PRODUCT_NAME: product_name,
    }
    if host is not None:
        record[CONF_HOST] = host
        record[CONF_PORT] = 3333
    return record


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com (test)",
        unique_id="test:user@example.com",
        data={
            CONF_ENVIRONMENT: "test",
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_DEVICES: {
                WELLY_ID: device_record(
                    "welly-token",
                    "Kitchen fountain",
                    "@klyqa.welly-dev",
                    WELLY_HOST,
                    "Klyqa Welly",
                ),
                FOODY_ID: device_record(
                    "foody-token", "Feeder", "@klyqa.foody-dev", FOODY_HOST, "Klyqa Foody"
                ),
                PURIFIER_ID: device_record(
                    "purifier-token",
                    "",
                    "@klyqa.cleaning.airpurifier1",
                    PURIFIER_HOST,
                    "Klyqa airpurifier",
                ),
            },
        },
        options={},
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry to hass and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
