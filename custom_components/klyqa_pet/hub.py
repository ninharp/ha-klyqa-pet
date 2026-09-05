"""Hub object: cloud token handling, mDNS browsing and per-device coordinators."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import logging
from typing import Any, cast

from homeassistant.components.zeroconf import async_get_async_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

    Stored host/port/product information survives; empty cloud values never overwrite
    stored values.
    """
    return {
        device_id: {**old.get(device_id, {}), **{k: v for k, v in record.items() if v}}
        for device_id, record in new.items()
    }


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

    async def async_setup(self) -> None:
        """Refresh tokens, create coordinators for known hosts and start mDNS browsing."""
        try:
            await self.async_refresh_tokens()
        except KlyqaAuthError as err:
            raise ConfigEntryAuthFailed("Klyqa cloud login failed") from err
        except KlyqaConnectionError as err:
            if not self.cloud_devices and not self.manual_devices:
                raise ConfigEntryNotReady(f"Cannot reach the Klyqa cloud: {err}") from err
            _LOGGER.warning("Klyqa cloud unreachable, using stored device tokens: %s", err)

        records = {**self.cloud_devices, **self.manual_devices}
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

    async def async_refresh_tokens(self) -> None:
        """Log in again and store fresh per-device tokens.

        Raises KlyqaAuthError or KlyqaConnectionError.
        """
        async with self._token_lock:
            fresh = await async_fetch_cloud_devices(
                self.hass,
                self.entry.data[CONF_ENVIRONMENT],
                self.entry.data[CONF_EMAIL],
                self.entry.data[CONF_PASSWORD],
            )
            merged = merge_device_records(self.cloud_devices, fresh)
            removed = set(self.cloud_devices) - set(merged)
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_DEVICES: merged}
            )
            for device_id, record in merged.items():
                if (coordinator := self.coordinators.get(device_id)) is not None:
                    coordinator.device.access_token = record[CONF_ACCESS_TOKEN]
            for device_id in removed:
                if not self.is_manual(device_id):
                    await self._async_remove_stale_device(device_id)

    async def _async_remove_stale_device(self, device_id: str) -> None:
        if (coordinator := self.coordinators.pop(device_id, None)) is not None:
            await coordinator.async_shutdown()
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier((DOMAIN, device_id), self.entry.entry_id)
        if device is not None:
            registry.async_remove_device(device.id)
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
        if (coordinator := self.coordinators.get(device_id)) is not None:
            if coordinator.device.host != discovered.host:
                _LOGGER.info("Device %s changed address to %s", device_id, discovered.host)
                coordinator.device.host = discovered.host
                self._persist_discovery(discovered)
                await coordinator.async_request_refresh()
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
        """Store host and product info of a cloud device so it comes up after a restart."""
        device_id = discovered.local_device_id
        if device_id not in self.cloud_devices:
            return  # manual devices carry their own host in the options
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
