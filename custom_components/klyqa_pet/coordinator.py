"""DataUpdateCoordinator for a single Klyqa device."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
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
    FoodyTimers,
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDevice,
    KlyqaDeviceError,
    KlyqaRateLimitError,
    StrypeDevice,
    StrypeState,
    SystemInfo,
    WellyDevice,
    WellySettings,
    WellyState,
)
from pyklyqa_pet.welly_timers import WellyTimers

from .const import (
    CONF_DEVICE_NAME,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SETTINGS_POLL_INTERVAL,
    SYSTEM_INFO_INTERVAL,
    TOKEN_RECOVERY_BACKOFF,
)

if TYPE_CHECKING:
    from .hub import KlyqaPetHub

_LOGGER = logging.getLogger(__name__)

type DeviceState = WellyState | FoodyState | AirPurifierState | StrypeState
type DeviceSettings = WellySettings | FoodySettings | None

_DEFAULT_PRODUCT_NAMES = {
    DeviceType.WELLY: "Klyqa Welly",
    DeviceType.FOODY: "Klyqa Foody",
    DeviceType.AIRPURIFIER: "Klyqa Airpurifier",
    DeviceType.STRYPE: "Klyqa Strype",
}


@dataclass(slots=True)
class KlyqaDeviceData:
    """Everything the entities need from one poll cycle."""

    system_info: SystemInfo
    state: DeviceState
    settings: DeviceSettings
    timers: FoodyTimers | WellyTimers | None

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
    def foody_timers(self) -> FoodyTimers:
        """Return the cached timer document as Foody timers."""
        assert isinstance(self.timers, FoodyTimers)
        return self.timers

    @property
    def welly_timers(self) -> WellyTimers:
        """Return the cached timer document as Welly timers."""
        assert isinstance(self.timers, WellyTimers)
        return self.timers

    @property
    def purifier(self) -> AirPurifierState:
        """Return the state as air purifier state."""
        assert isinstance(self.state, AirPurifierState)
        return self.state

    @property
    def strype(self) -> StrypeState:
        """Return the state as Strype state."""
        assert isinstance(self.state, StrypeState)
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
        # The options-flow selector can only ever store an int within
        # [MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL], but the option can also be reached by
        # editing .storage directly or via a programmatic async_update_entry, which
        # bypasses that validation entirely. Clamp/fall back here so a bad value (0, a
        # negative number, a non-numeric string, or an out-of-range value) can never
        # produce a zero/negative update_interval or a setup-time TypeError.
        raw_scan_interval: Any = entry.options.get(CONF_SCAN_INTERVAL)
        try:
            scan_interval_seconds = int(raw_scan_interval)
        except (TypeError, ValueError):
            scan_interval_seconds = int(DEFAULT_SCAN_INTERVAL.total_seconds())
        scan_interval_seconds = min(
            max(scan_interval_seconds, MIN_SCAN_INTERVAL), MAX_SCAN_INTERVAL
        )
        update_interval = timedelta(seconds=scan_interval_seconds)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {local_device_id}",
            update_interval=update_interval,
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
        # Cached timer document for Welly and Foody devices only, refreshed on the same
        # cadence as settings (see _async_fetch): timers change rarely and only through
        # the app, Home Assistant or the device's own buttons, and every write here
        # refreshes them directly, so there is no need to poll device/timer any more
        # often than settings.
        self._timers: FoodyTimers | WellyTimers | None = None
        self._poll_count = 0
        # Strype only: the last state published for this device. The lighting firmware
        # answers every request with a mode-dependent status message - `color` only in
        # rgb mode, `temperature` only in cct mode, neither in cmd mode - and offers no
        # endpoint that reports both, so each response is merged onto this one rather
        # than replacing it (see StrypeState.from_dict).
        self._strype_state: StrypeState | None = None
        # dt_util.utcnow() (not time.monotonic()) so tests can control this clock with
        # freezegun; monotonic() is untouched by freezegun and made the cache gate
        # untestable.
        self._system_info_time: datetime = datetime.min.replace(tzinfo=dt_util.UTC)
        self._token_warned = False
        # Serialises a read-modify-write sequence against this device. The library only
        # serialises individual requests, so two services that each read the timer
        # document, compute from it and write it back would interleave at their awaits -
        # two parallel schedule adds would claim the same free slot, and two parallel
        # changes to one slot would each overwrite the other's. Whoever reads in order to
        # write holds this across the whole sequence.
        self.write_lock = asyncio.Lock()
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

    @property
    def strype_device(self) -> StrypeDevice:
        """Return the device client as Strype client."""
        assert isinstance(self.device, StrypeDevice)
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

    def mark_timers_stale(self) -> None:
        """Force the next poll to reload the timer document instead of the cached copy.

        Two callers. The feeding-schedule services call it after a successful write and
        then request a refresh, so the new schedule list is on screen without waiting
        for the next periodic timers poll. Both they and the entities also call it when
        a write *fails*: the firmware changes its own copy before the step that can fail
        (device_timers.c), so a rejected write may already have moved the device, and
        the cached document can no longer be trusted. That path asks for no refresh -
        the re-read is left to the next scheduled poll.

        A successful entity write does not come through here at all: it publishes the
        document the device returned (see async_publish_timers).
        """
        self._timers = None

    @callback
    def async_publish_timers(self, timers: FoodyTimers | WellyTimers) -> None:
        """Publish the timer document a timer write returned.

        The firmware answers every accepted timer write with the complete, freshly
        serialised document (`device_timers_set_json` ends by calling
        `device_timers_get_json`), so the write's own response is already the whole
        truth and can be published straight away - no extra request, and no waiting for
        a refresh that the request debouncer may swallow. Publishing also keeps the
        cache authoritative: without it, a burst of writes within the debouncer's
        cooldown would each be built from the same pre-burst snapshot and quietly undo
        one another.
        """
        self._timers = timers
        self.async_set_updated_data(replace(self.data, timers=timers))

    @property
    def strype_state(self) -> StrypeState | None:
        """Return the last known Strype state, to merge the next response onto."""
        return self._strype_state

    @callback
    def async_publish_strype_state(self, state: StrypeState) -> None:
        """Publish the state a Strype write returned.

        The library has already merged the device's response onto the state passed in as
        `previous=` (this coordinator's own), so `state` is a complete picture and can be
        published straight away. That is both faster for the user and gentler on the
        firmware's rate limit than following every write with another request.
        """
        self._strype_state = state
        self.async_set_updated_data(replace(self.data, state=state))

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
        timers: FoodyTimers | WellyTimers | None = None
        state: DeviceState
        if isinstance(self.device, WellyDevice | FoodyDevice):
            state = await self.device.get_state()
            self._poll_count += 1
            if self._settings is None or self._poll_count % SETTINGS_POLL_INTERVAL == 0:
                self._settings = await self.device.get_settings()
            settings = self._settings
            if self.device_type in (DeviceType.FOODY, DeviceType.WELLY):
                # Timers ride the same infrequent cadence as settings: they change
                # rarely and only through the app, Home Assistant or the device's own
                # buttons, and a write from here never waits for this poll to be seen -
                # the schedule/timer services mark the cache stale and refresh, the
                # sleep/timer entities publish the document the device returned with
                # their write. Only a failed write, or a change made in the Klyqa app,
                # leaves anything for this poll to pick up, so there is no need to read
                # device/timer any more often than settings.
                if self._timers is None or self._poll_count % SETTINGS_POLL_INTERVAL == 0:
                    self._timers = await self.device.get_timers()
                timers = self._timers
        elif isinstance(self.device, AirPurifierDevice):
            state = await self.device.get_state()
        elif isinstance(self.device, StrypeDevice):
            # There is no state GET on the lighting firmware: a read is a command that
            # carries no state-changing field, answered with the same mode-dependent
            # status message a write returns. Merge it onto what we already knew.
            state = await self.device.get_state(previous=self._strype_state)
            self._strype_state = state
        else:  # pragma: no cover - guarded by create_device
            raise UpdateFailed(f"Unsupported device class {type(self.device).__name__}")
        return KlyqaDeviceData(
            system_info=self._system_info, state=state, settings=settings, timers=timers
        )

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
