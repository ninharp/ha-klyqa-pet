"""DataUpdateCoordinator for a single Klyqa device."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pyklyqa_pet import (
    AirPurifierDevice,
    AirPurifierState,
    DeviceType,
    FoodyDevice,
    FoodySettings,
    FoodyState,
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDevice,
    KlyqaDeviceError,
    SystemInfo,
    WellyDevice,
    WellySettings,
    WellyState,
)

from .const import (
    CONF_DEVICE_NAME,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    DOMAIN,
    SCAN_INTERVAL,
    SYSTEM_INFO_INTERVAL,
)

if TYPE_CHECKING:
    from .hub import KlyqaPetHub

_LOGGER = logging.getLogger(__name__)

type DeviceState = WellyState | FoodyState | AirPurifierState
type DeviceSettings = WellySettings | FoodySettings | None

_DEFAULT_PRODUCT_NAMES = {
    DeviceType.WELLY: "Klyqa Welly",
    DeviceType.FOODY: "Klyqa Foody",
    DeviceType.AIRPURIFIER: "Klyqa Airpurifier",
}


@dataclass(slots=True)
class KlyqaDeviceData:
    """Everything the entities need from one poll cycle."""

    system_info: SystemInfo
    state: DeviceState
    settings: DeviceSettings

    @property
    def welly(self) -> WellyState:
        """Return the state as Welly state."""
        assert isinstance(self.state, WellyState)
        return self.state

    @property
    def welly_settings(self) -> WellySettings:
        """Return the settings as Welly settings."""
        assert isinstance(self.settings, WellySettings)
        return self.settings

    @property
    def foody(self) -> FoodyState:
        """Return the state as Foody state."""
        assert isinstance(self.state, FoodyState)
        return self.state

    @property
    def foody_settings(self) -> FoodySettings:
        """Return the settings as Foody settings."""
        assert isinstance(self.settings, FoodySettings)
        return self.settings

    @property
    def purifier(self) -> AirPurifierState:
        """Return the state as air purifier state."""
        assert isinstance(self.state, AirPurifierState)
        return self.state


class KlyqaDeviceCoordinator(DataUpdateCoordinator[KlyqaDeviceData]):
    """Poll one device for state, settings and (rarely) system info."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: KlyqaPetHub,
        local_device_id: str,
        device_type: DeviceType,
        device: KlyqaDevice,
        record: dict[str, Any],
        *,
        is_manual: bool,
    ) -> None:
        """Initialise the coordinator for one device."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {local_device_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.hub = hub
        self.local_device_id = local_device_id
        self.device_type = device_type
        self.device = device
        self.is_manual = is_manual
        self.product_id: str = record.get(CONF_PRODUCT_ID, "")
        self.product_name: str = (
            record.get(CONF_PRODUCT_NAME) or _DEFAULT_PRODUCT_NAMES[device_type]
        )
        self.device_name: str = (
            record.get(CONF_DEVICE_NAME) or f"{self.product_name} {local_device_id[-6:]}"
        )
        self.dispense_portions: int = 1
        self._system_info: SystemInfo | None = None
        self._system_info_time = 0.0

    @property
    def welly_device(self) -> WellyDevice:
        """Return the device client as Welly client."""
        assert isinstance(self.device, WellyDevice)
        return self.device

    @property
    def foody_device(self) -> FoodyDevice:
        """Return the device client as Foody client."""
        assert isinstance(self.device, FoodyDevice)
        return self.device

    @property
    def purifier_device(self) -> AirPurifierDevice:
        """Return the device client as air purifier client."""
        assert isinstance(self.device, AirPurifierDevice)
        return self.device

    async def _async_update_data(self) -> KlyqaDeviceData:
        try:
            return await self._async_fetch()
        except KlyqaAuthError as err:
            if self.is_manual:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="device_auth_failed",
                    translation_placeholders={"device": self.device_name},
                ) from err
            await self._async_recover_token()
            try:
                return await self._async_fetch()
            except KlyqaAuthError as retry_err:
                raise ConfigEntryAuthFailed(
                    f"Device {self.device_name} still rejects the refreshed token"
                ) from retry_err
            except (KlyqaConnectionError, KlyqaDeviceError) as retry_err:
                raise self._update_failed(retry_err) from retry_err
        except (KlyqaConnectionError, KlyqaDeviceError) as err:
            raise self._update_failed(err) from err

    def _update_failed(self, err: Exception) -> UpdateFailed:
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"device": self.device_name, "error": str(err)},
        )

    async def _async_recover_token(self) -> None:
        """Fetch fresh tokens from the cloud after the device rejected ours."""
        _LOGGER.debug(
            "Device %s rejected its token, refreshing from the cloud", self.local_device_id
        )
        try:
            await self.hub.async_refresh_tokens()
        except KlyqaAuthError as err:
            raise ConfigEntryAuthFailed(
                "Cloud login failed while refreshing device tokens"
            ) from err
        except KlyqaConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="token_refresh_failed",
                translation_placeholders={"device": self.device_name},
            ) from err

    async def _async_fetch(self) -> KlyqaDeviceData:
        now = monotonic()
        if (
            self._system_info is None
            or now - self._system_info_time >= SYSTEM_INFO_INTERVAL.total_seconds()
        ):
            self._system_info = await self.device.get_system_info()
            self._system_info_time = now
            self._async_update_device_registry(self._system_info)

        settings: DeviceSettings = None
        state: DeviceState
        if isinstance(self.device, WellyDevice | FoodyDevice):
            state = await self.device.get_state()
            settings = await self.device.get_settings()
        elif isinstance(self.device, AirPurifierDevice):
            state = await self.device.get_state()
        else:  # pragma: no cover - guarded by create_device
            raise UpdateFailed(f"Unsupported device class {type(self.device).__name__}")
        return KlyqaDeviceData(system_info=self._system_info, state=state, settings=settings)

    @callback
    def _async_update_device_registry(self, info: SystemInfo) -> None:
        """Keep firmware/hardware versions in the device registry current."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.local_device_id), self.config_entry.entry_id
        )
        if device is None:
            return
        registry.async_update_device(
            device.id,
            sw_version=info.app_version or None,
            hw_version=str(info.hw_revision) if info.hw_revision else None,
            serial_number=str(info.serial_number) if info.serial_number else None,
        )
