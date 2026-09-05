"""Hub object: cloud token handling, mDNS browsing and per-device coordinators."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
import logging
from typing import Any, cast

from homeassistant.components.zeroconf import async_get_async_instance
from homeassistant.config_entries import SOURCE_ZEROCONF, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from pyklyqa_pet import (
    DEFAULT_PORT,
    ZEROCONF_TYPE,
    DiscoveredDevice,
    Environment,
    KlyqaAuthError,
    KlyqaCloudClient,
    KlyqaConnectionError,
    create_device,
    device_type_from_product_id,
    parse_zeroconf_properties,
)

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_ENVIRONMENT,
    CONF_MANUAL_DEVICES,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    DOMAIN,
    ENVIRONMENT_LOCAL,
    TOKEN_REFRESH_COALESCE,
)
from .coordinator import KlyqaDeviceCoordinator

_LOGGER = logging.getLogger(__name__)

type DeviceRecord = dict[str, Any]
type NewDeviceListener = Callable[[KlyqaDeviceCoordinator], None]


async def async_fetch_cloud_devices(
    hass: HomeAssistant, environment: str, email: str, password: str
) -> dict[str, DeviceRecord]:
    """Log in to the cloud and return device records keyed by local device id."""
    client = KlyqaCloudClient(async_get_clientsession(hass), Environment(environment))
    await client.login(email, password)
    return {
        device.local_device_id: {
            CONF_ACCESS_TOKEN: device.access_token,
            CONF_DEVICE_NAME: device.name,
            CONF_PRODUCT_ID: device.product_id,
        }
        for device in await client.list_devices()
    }


def merge_device_records(
    old: dict[str, DeviceRecord], new: dict[str, DeviceRecord]
) -> dict[str, DeviceRecord]:
    """Overlay fresh cloud records on stored ones and drop devices the cloud no longer lists.

    Stored host/port information survives; empty cloud values never overwrite stored
    values. The product id/name are facts the device itself announces over mDNS, and the
    cloud's product catalogue entry for a device can disagree with that (e.g. a device
    reporting `@pfriendly.airpurifier-dev` while the cloud lists it under a different
    internal product id) - once a non-empty stored value exists, the cloud only fills the
    gap, it never overrides it.
    """
    merged: dict[str, DeviceRecord] = {}
    for device_id, record in new.items():
        stored = old.get(device_id, {})
        result = {**stored, **{k: v for k, v in record.items() if v}}
        for key in (CONF_PRODUCT_ID, CONF_PRODUCT_NAME):
            if stored.get(key):
                result[key] = stored[key]
        merged[device_id] = result
    return merged


def _async_remove_device_registry_entry(hass: HomeAssistant, device_id: str, entry_id: str) -> None:
    """Remove one config entry's device-registry entry for a device, if any."""
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier((DOMAIN, device_id), entry_id)
    if device is not None:
        registry.async_remove_device(device.id)


async def async_release_device_from_other_entries(
    hass: HomeAssistant, device_id: str, except_entry_id: str
) -> None:
    """Make every other loaded klyqa_pet entry give up a device it owns as a cloud record.

    A device must be owned by exactly one config entry. When it is claimed elsewhere
    (typically: added manually to a local entry), every other loaded entry that still
    lists it as a cloud record must drop its device-registry entry for it and reload,
    so its own `_is_claimed_elsewhere` check keeps the device out from then on.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == except_entry_id:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if device_id not in entry.data.get(CONF_DEVICES, {}):
            continue
        _async_remove_device_registry_entry(hass, device_id, entry.entry_id)
        hass.config_entries.async_schedule_reload(entry.entry_id)


class KlyqaPetHub:
    """Runtime object of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Create the hub for a config entry."""
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self.coordinators: dict[str, KlyqaDeviceCoordinator] = {}
        self._listeners: list[NewDeviceListener] = []
        self._browser: AsyncServiceBrowser | None = None
        self._resolve_tasks: set[asyncio.Task[None]] = set()
        self._pending: set[str] = set()
        self._token_lock = asyncio.Lock()
        self._last_token_refresh: datetime | None = None

    @property
    def cloud_devices(self) -> dict[str, DeviceRecord]:
        """Return device records that came from the cloud account."""
        result: dict[str, DeviceRecord] = self.entry.data.get(CONF_DEVICES, {})
        return result

    @property
    def manual_devices(self) -> dict[str, DeviceRecord]:
        """Return device records added manually through the options flow."""
        result: dict[str, DeviceRecord] = self.entry.options.get(CONF_MANUAL_DEVICES, {})
        return result

    def get_record(self, local_device_id: str) -> DeviceRecord | None:
        """Return the record of a known device (manual records win)."""
        return self.manual_devices.get(local_device_id) or self.cloud_devices.get(local_device_id)

    def is_manual(self, local_device_id: str) -> bool:
        """Return True if the device was added manually."""
        return local_device_id in self.manual_devices

    @property
    def is_local(self) -> bool:
        """Return True if this entry has no cloud account (devices added by IP + token)."""
        return self.entry.data.get(CONF_ENVIRONMENT) == ENVIRONMENT_LOCAL

    def _is_claimed_elsewhere(self, device_id: str) -> bool:
        """Return True if another config entry manually claims this device.

        A device claimed by a local entry (added there by IP + token) must never also
        be polled with a cloud token by an account entry that happens to list the same
        id - the manual entry's record is authoritative for it.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self.entry.entry_id:
                continue
            if device_id in entry.options.get(CONF_MANUAL_DEVICES, {}):
                return True
        return False

    async def async_setup(self) -> None:
        """Refresh tokens, create coordinators for known hosts and start mDNS browsing."""
        if not self.is_local:
            try:
                await self.async_refresh_tokens(force=True)
            except KlyqaAuthError as err:
                raise ConfigEntryAuthFailed("Klyqa cloud login failed") from err
            except KlyqaConnectionError as err:
                if not self.cloud_devices and not self.manual_devices:
                    raise ConfigEntryNotReady(f"Cannot reach the Klyqa cloud: {err}") from err
                _LOGGER.warning("Klyqa cloud unreachable, using stored device tokens: %s", err)

        cloud_devices = {
            device_id: record
            for device_id, record in self.cloud_devices.items()
            if not self._is_claimed_elsewhere(device_id)
        }
        for device_id in set(self.cloud_devices) - set(cloud_devices):
            _LOGGER.debug("Skipping %s: claimed by another entry", device_id)
            # A device claimed elsewhere must never leave a stale device-registry entry
            # under this entry (e.g. an orphaned device card after a manual add moved
            # ownership away from this account entry).
            _async_remove_device_registry_entry(self.hass, device_id, self.entry.entry_id)

        records = {**cloud_devices, **self.manual_devices}
        await asyncio.gather(
            *(
                self._async_add_coordinator(device_id, record)
                for device_id, record in records.items()
                if record.get(CONF_HOST)
            )
        )

        aiozc = await async_get_async_instance(self.hass)
        self._browser = AsyncServiceBrowser(
            aiozc.zeroconf, ZEROCONF_TYPE, handlers=[self._on_service_state_change]
        )

    async def async_shutdown(self) -> None:
        """Stop browsing and all coordinators."""
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None
        for task in self._resolve_tasks:
            task.cancel()
        for coordinator in self.coordinators.values():
            await coordinator.async_shutdown()

    @callback
    def async_add_new_device_listener(self, listener: NewDeviceListener) -> Callable[[], None]:
        """Register a callback invoked when a coordinator for a new device is created."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    async def async_refresh_tokens(self, force: bool = False) -> None:
        """Log in again and store fresh per-device tokens.

        Several devices rejecting their token in the same poll cycle must not each
        trigger their own cloud login: unless `force` is set, a refresh that happened
        less than TOKEN_REFRESH_COALESCE ago is skipped and the stored tokens are kept
        as they are. Setup uses `force=True` because it needs a guaranteed fresh login;
        a forced refresh does not itself start the coalescing window, so a coordinator
        that genuinely needs a fresh token shortly after setup (e.g. a device whose
        token was rotated) is never blocked by the setup login.

        Raises KlyqaAuthError or KlyqaConnectionError.
        """
        if self.is_local:
            # A local entry has no cloud account to refresh tokens from; its devices
            # keep the token they were added with.
            return
        async with self._token_lock:
            now = dt_util.utcnow()
            if (
                not force
                and self._last_token_refresh is not None
                and now - self._last_token_refresh < TOKEN_REFRESH_COALESCE
            ):
                return
            fresh = await async_fetch_cloud_devices(
                self.hass,
                self.entry.data[CONF_ENVIRONMENT],
                self.entry.data[CONF_EMAIL],
                self.entry.data[CONF_PASSWORD],
            )
            if not force:
                self._last_token_refresh = dt_util.utcnow()
            if not fresh and self.cloud_devices:
                # A transient empty response (e.g. a cloud hiccup) must never be read as
                # "the account lost all its devices" - keep everything as it is.
                _LOGGER.warning(
                    "Klyqa cloud returned no devices for this account, keeping the stored devices"
                )
                return
            merged = merge_device_records(self.cloud_devices, fresh)
            removed = set(self.cloud_devices) - set(merged)
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_DEVICES: merged}
            )
            for device_id in merged:
                self._async_abort_discovery_flow(device_id)
            for device_id, record in merged.items():
                if self.is_manual(device_id):
                    # A manually added device keeps the token it was given; the cloud
                    # must never overwrite it even if the account happens to list the
                    # same id.
                    continue
                if (coordinator := self.coordinators.get(device_id)) is not None:
                    coordinator.device.access_token = record[CONF_ACCESS_TOKEN]
            for device_id in removed:
                if not self.is_manual(device_id):
                    await self._async_remove_stale_device(device_id)

    async def async_remove_manual_device(self, device_id: str) -> None:
        """Forget a manually added device."""
        if (coordinator := self.coordinators.pop(device_id, None)) is not None:
            await coordinator.async_shutdown()
        manual = {k: v for k, v in self.manual_devices.items() if k != device_id}
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_MANUAL_DEVICES: manual}
        )

    async def _async_remove_stale_device(self, device_id: str) -> None:
        if (coordinator := self.coordinators.pop(device_id, None)) is not None:
            await coordinator.async_shutdown()
        _async_remove_device_registry_entry(self.hass, device_id, self.entry.entry_id)
        _LOGGER.info("Removed device %s that is no longer part of the Klyqa account", device_id)

    @callback
    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        task = self.hass.async_create_background_task(
            self._async_resolve(zeroconf, service_type, name), f"{DOMAIN} resolve {name}"
        )
        self._resolve_tasks.add(task)
        task.add_done_callback(self._resolve_tasks.discard)

    async def _async_resolve(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(zeroconf, 3000):
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not addresses:
            return
        # zeroconf types the TXT records as dict[bytes, bytes | None]; the library accepts
        # a wider Mapping, which mypy rejects because Mapping keys are invariant.
        properties = cast("Mapping[str | bytes, str | bytes | None]", info.properties)
        discovered = parse_zeroconf_properties(addresses[0], info.port, properties)
        if discovered is not None:
            await self.async_device_discovered(discovered)

    @callback
    def _async_abort_discovery_flow(self, device_id: str) -> None:
        """Abort a pending discovery flow for a device that now belongs to this entry.

        HA core's zeroconf discovery can start its own config flow for a device before
        any account claims it. Once the hub sees (via its own mDNS browser or a cloud
        token refresh) that the device is now part of this entry, that stale discovery
        flow must be aborted - otherwise it stays listed as "Discovered" until clicked.
        A no-op when no such flow exists.
        """
        unique_id = f"discovered:{device_id}"
        for flow in self.hass.config_entries.flow.async_progress_by_handler(
            DOMAIN, include_uninitialized=True, match_context={"source": SOURCE_ZEROCONF}
        ):
            if flow["context"].get("unique_id") == unique_id:
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def async_device_discovered(self, discovered: DiscoveredDevice) -> None:
        """Handle a supported device seen on the LAN."""
        device_id = discovered.local_device_id
        record = self.get_record(device_id)
        if record is None:
            _LOGGER.debug(
                "Ignoring %s (%s at %s): not part of this account",
                device_id,
                discovered.product_id,
                discovered.host,
            )
            return
        self._async_abort_discovery_flow(device_id)
        if not self.is_manual(device_id) and self._is_claimed_elsewhere(device_id):
            _LOGGER.debug("Ignoring %s: claimed by another entry", device_id)
            _async_remove_device_registry_entry(self.hass, device_id, self.entry.entry_id)
            return
        if (coordinator := self.coordinators.get(device_id)) is not None:
            host_changed = coordinator.device.host != discovered.host
            # KlyqaDevice.port has no setter (it is fixed at construction time in the
            # library), so a changed port cannot be applied to the live device object.
            # Persisting it below still keeps the config entry accurate; it only takes
            # effect after the next restart, when the coordinator is recreated from the
            # stored record.
            port_changed = discovered.port != coordinator.device.port
            if host_changed or port_changed:
                self._persist_discovery(discovered)
            if host_changed:
                _LOGGER.info("Device %s changed address to %s", device_id, discovered.host)
                coordinator.device.host = discovered.host
                await coordinator.async_request_refresh()
            if port_changed:
                _LOGGER.info(
                    "Device %s changed port to %s; this applies after the next restart",
                    device_id,
                    discovered.port,
                )
            return
        if device_id in self._pending:
            return
        self._pending.add(device_id)
        try:
            self._persist_discovery(discovered)
            record = {
                **record,
                CONF_HOST: discovered.host,
                CONF_PORT: discovered.port,
                CONF_PRODUCT_ID: discovered.product_id,
                CONF_PRODUCT_NAME: discovered.product_name or record.get(CONF_PRODUCT_NAME, ""),
                CONF_DEVICE_NAME: record.get(CONF_DEVICE_NAME) or discovered.device_name,
            }
            await self._async_add_coordinator(device_id, record)
        finally:
            self._pending.discard(device_id)

    @callback
    def _persist_discovery(self, discovered: DiscoveredDevice) -> None:
        """Store host and product info of a device so it comes up after a restart."""
        device_id = discovered.local_device_id
        if device_id in self.manual_devices:
            current_manual = self.manual_devices[device_id]
            updated_manual = {
                **current_manual,
                CONF_HOST: discovered.host,
                CONF_PORT: discovered.port,
            }
            if updated_manual != current_manual:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    options={
                        **self.entry.options,
                        CONF_MANUAL_DEVICES: {**self.manual_devices, device_id: updated_manual},
                    },
                )
            return
        if device_id not in self.cloud_devices:
            return
        current = self.cloud_devices[device_id]
        updated = {
            **current,
            CONF_HOST: discovered.host,
            CONF_PORT: discovered.port,
            CONF_PRODUCT_ID: discovered.product_id,
            CONF_PRODUCT_NAME: discovered.product_name or current.get(CONF_PRODUCT_NAME, ""),
        }
        if updated != current:
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_DEVICES: {**self.cloud_devices, device_id: updated}},
            )

    async def _async_add_coordinator(self, device_id: str, record: DeviceRecord) -> None:
        device_type = device_type_from_product_id(record.get(CONF_PRODUCT_ID, ""))
        if device_type is None:
            _LOGGER.debug(
                "Skipping %s: unsupported product id %r", device_id, record.get(CONF_PRODUCT_ID)
            )
            return
        device = create_device(
            device_type,
            self.session,
            record[CONF_HOST],
            record[CONF_ACCESS_TOKEN],
            record.get(CONF_PORT, DEFAULT_PORT),
        )
        coordinator = KlyqaDeviceCoordinator(
            self.hass,
            self.entry,
            self,
            device_id,
            device_type,
            device,
            record,
            is_manual=self.is_manual(device_id),
        )
        await coordinator.async_refresh()
        self.coordinators[device_id] = coordinator
        for listener in list(self._listeners):
            listener(coordinator)
