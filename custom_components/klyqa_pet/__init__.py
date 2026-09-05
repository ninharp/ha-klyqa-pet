"""The Klyqa Pet integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
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
