"""The Klyqa Pet integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import translation

from pyklyqa_pet import CloudApp

from .const import (
    CONF_CLOUD_APP,
    CONF_DEVICES,
    CONF_ENVIRONMENT,
    CONF_MANUAL_DEVICES,
    DOMAIN,
    ENVIRONMENT_LOCAL,
    LOCAL_ENTRY_UNIQUE_ID,
    MINOR_VERSION,
    PLATFORMS,
)
from .hub import KlyqaPetHub

_LOGGER = logging.getLogger(__name__)

type KlyqaPetConfigEntry = ConfigEntry[KlyqaPetHub]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry created before the cloud tenant became part of its identity.

    A cloud entry's unique id used to be "<environment>:<email>"; it is now
    "<environment>:<tenant>:<email>", because the same account sees a different set
    of devices per tenant and must therefore be addable once per tenant. Without
    this migration an existing entry keeps the old id forever, and re-adding the
    same account no longer aborts as already configured - leaving two entries (and
    so two coordinators) fighting over the same rate-limited devices.
    """
    if entry.minor_version >= MINOR_VERSION:
        return True
    unique_id = entry.unique_id
    if (
        unique_id is None
        or unique_id == LOCAL_ENTRY_UNIQUE_ID
        or entry.data.get(CONF_ENVIRONMENT) == ENVIRONMENT_LOCAL
        or unique_id.count(":") != 1
    ):
        # A local-only entry, or an id that already carries the tenant.
        hass.config_entries.async_update_entry(entry, minor_version=MINOR_VERSION)
        return True
    environment, email = unique_id.split(":")
    # Legacy entries predate the tenant selector entirely, so they can only ever
    # have been created against the pet tenant; record it in the data too.
    cloud_app = entry.data.get(CONF_CLOUD_APP, CloudApp.KLYQAPET.value)
    new_unique_id = f"{environment}:{cloud_app}:{email}"
    if any(
        other.entry_id != entry.entry_id and other.unique_id == new_unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        # Home Assistant only migrates entries it sets up, so a disabled or ignored
        # legacy entry is skipped. If the same account was added fresh in the meantime
        # and the legacy entry is enabled again later, the rewrite would land on an id
        # that is already taken - which HA logs as an error and then carries on with,
        # leaving two entries sharing one unique id. Leave the id alone in that case;
        # the entry is a duplicate the user can remove.
        _LOGGER.warning(
            "Not migrating config entry unique id %s to %s: another entry already uses it",
            unique_id,
            new_unique_id,
        )
        hass.config_entries.async_update_entry(entry, minor_version=MINOR_VERSION)
        return True
    _LOGGER.debug("Migrating config entry unique id %s to %s", unique_id, new_unique_id)
    hass.config_entries.async_update_entry(
        entry,
        unique_id=new_unique_id,
        data={**entry.data, CONF_CLOUD_APP: cloud_app},
        minor_version=MINOR_VERSION,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KlyqaPetConfigEntry) -> bool:
    """Set up Klyqa Pet from a config entry."""
    # hub.async_setup() below immediately refreshes every known device's coordinator,
    # which can raise a translated UpdateFailed/HomeAssistantError. HA's own translation
    # cache for this integration is normally ready by the time a config entry is set up,
    # but under load at startup the bulk background load kicked off for every integration
    # in bootstrap.async_setup_multi_components can still be in flight, and the fallback
    # load in homeassistant.setup._async_setup_component queues up behind the same lock -
    # so the very first refresh can race it and log a bare translation key (e.g.
    # "update_failed") instead of the rendered message. Loading our own translations here
    # is cheap (a no-op once cached) and guarantees they are ready before any device is
    # touched.
    await translation.async_load_integrations(hass, {DOMAIN})
    hub = KlyqaPetHub(hass, entry)
    await hub.async_setup()
    entry.runtime_data = hub
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # Platform forwarding failed partway through: don't leak the hub's mDNS
        # browser and coordinators, they would otherwise keep running with nothing
        # ever calling async_unload_entry to clean them up.
        await hub.async_shutdown()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KlyqaPetConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: KlyqaPetConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that are gone from the account or were added manually."""
    if entry.state is not ConfigEntryState.LOADED:
        # No hub/coordinators to consult; decide purely from what is stored on the entry.
        manual_devices = entry.options.get(CONF_MANUAL_DEVICES, {})
        cloud_devices = entry.data.get(CONF_DEVICES, {})
        for domain, device_id in device_entry.identifiers:
            if domain != DOMAIN:
                continue
            if device_id in manual_devices:
                remaining = {k: v for k, v in manual_devices.items() if k != device_id}
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, CONF_MANUAL_DEVICES: remaining}
                )
            elif device_id in cloud_devices:
                return False
        return True

    hub = entry.runtime_data
    for domain, device_id in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if hub.is_manual(device_id):
            await hub.async_remove_manual_device(device_id)
        elif device_id in hub.cloud_devices:
            # A cloud device is never removable while the account still lists it, even
            # if mDNS hasn't discovered a host for it yet and no coordinator exists.
            return False
    return True
