"""The Klyqa Pet integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_DEVICES, CONF_MANUAL_DEVICES, DOMAIN, PLATFORMS
from .hub import KlyqaPetHub

type KlyqaPetConfigEntry = ConfigEntry[KlyqaPetHub]


async def async_setup_entry(hass: HomeAssistant, entry: KlyqaPetConfigEntry) -> bool:
    """Set up Klyqa Pet from a config entry."""
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
