"""DataUpdateCoordinator for a single Klyqa device."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    KlyqaRateLimitError,
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
    SETTINGS_POLL_INTERVAL,
    SYSTEM_INFO_INTERVAL,
    TOKEN_RECOVERY_BACKOFF,
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
        # Cached settings for Welly/Foody devices, refreshed only every
        # SETTINGS_POLL_INTERVAL polls (see _async_fetch) to reduce REST pressure; a
        # settings write marks this stale so the very next poll reloads it.
        self._settings: DeviceSettings = None
        self._poll_count = 0
        # dt_util.utcnow() (not time.monotonic()) so tests can control this clock with
        # freezegun; monotonic() is untouched by freezegun and made the cache gate
        # untestable.
        self._system_info_time: datetime = datetime.min.replace(tzinfo=dt_util.UTC)
        self._token_warned = False
        # Set after a cloud token recovery still leaves the device rejecting its token;
        # until this passes, a 401 fails the update directly without asking the hub for
        # another cloud login (see async_refresh_tokens coalescing on the hub side too).
        self._next_token_recovery: datetime | None = None

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
            data = await self._async_fetch()
        except KlyqaAuthError as err:
            if self.is_manual:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="device_auth_failed",
                    translation_placeholders={"device": self.device_name},
                ) from err
            if (
                self._next_token_recovery is not None
                and dt_util.utcnow() < self._next_token_recovery
            ):
                # Still backed off from the last failed recovery: fail this poll
                # directly, without asking the hub for another cloud login.
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="device_auth_failed",
                    translation_placeholders={"device": self.device_name},
                ) from err
            await self._async_recover_token()
            try:
                data = await self._async_fetch()
            except KlyqaAuthError as retry_err:
                # The cloud login succeeded, so this is a per-device problem (e.g. the
                # device was re-paired to a different account) and must not put the
                # whole config entry into reauth. Back off further recoveries for this
                # device so a persistently rejecting device does not trigger a fresh
                # cloud login on every poll cycle.
                self._next_token_recovery = dt_util.utcnow() + TOKEN_RECOVERY_BACKOFF
                if not self._token_warned:
                    _LOGGER.warning(
                        "Device %s (%s) rejects the access token from the Klyqa "
                        "account; re-pair the device in the Klyqa app",
                        self.device_name,
                        self.local_device_id,
                    )
                    self._token_warned = True
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="device_auth_failed",
                    translation_placeholders={"device": self.device_name},
                ) from retry_err
            except (KlyqaConnectionError, KlyqaDeviceError) as retry_err:
                raise self._update_failed(retry_err) from retry_err
        except (KlyqaConnectionError, KlyqaDeviceError) as err:
            raise self._update_failed(err) from err
        self._token_warned = False
        self._next_token_recovery = None
        return data

    def _update_failed(self, err: Exception) -> UpdateFailed:
        if isinstance(err, KlyqaRateLimitError):
            # The library already retried a couple of times before giving up; a device
            # keeps rejecting requests only when something else (the Klyqa app, another
            # HA entry) is also polling it at the same time.
            return UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={"device": self.device_name},
            )
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"device": self.device_name, "error": str(err)},
        )

    def mark_settings_stale(self) -> None:
        """Force the next poll to reload settings instead of reusing the cached copy.

        Called after a settings write so the change is reflected as soon as the write's
        automatic refresh runs, without waiting for the next periodic settings poll.
        """
        self._settings = None

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
        now = dt_util.utcnow()
        if self._system_info is None or now - self._system_info_time >= SYSTEM_INFO_INTERVAL:
            self._system_info = await self.device.get_system_info()
            self._system_info_time = now
            self._async_update_device_registry(self._system_info)

        settings: DeviceSettings = None
        state: DeviceState
        if isinstance(self.device, WellyDevice | FoodyDevice):
            state = await self.device.get_state()
            self._poll_count += 1
            if self._settings is None or self._poll_count % SETTINGS_POLL_INTERVAL == 0:
                self._settings = await self.device.get_settings()
            settings = self._settings
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
