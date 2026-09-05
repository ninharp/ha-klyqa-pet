"""Diagnostics support for Klyqa Pet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import KlyqaPetConfigEntry
from .const import CONF_ACCESS_TOKEN, DOMAIN
from .coordinator import KlyqaDeviceCoordinator

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_ACCESS_TOKEN}


def _coordinator_diagnostics(coordinator: KlyqaDeviceCoordinator) -> dict[str, Any]:
    data = coordinator.data
    return {
        "local_device_id": coordinator.local_device_id,
        "device_type": coordinator.device_type.value,
        "device_name": coordinator.device_name,
        "product_id": coordinator.product_id,
        "host": coordinator.device.host,
        "port": coordinator.device.port,
        "is_manual": coordinator.is_manual,
        "last_update_success": coordinator.last_update_success,
        "system_info": data.system_info.raw if data else None,
        "state": data.state.raw if data else None,
        "settings": data.settings.raw if data and data.settings else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KlyqaPetConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    hub = getattr(entry, "runtime_data", None)
    result: dict[str, Any] = {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "entry_state": entry.state.value,
        "devices": [_coordinator_diagnostics(c) for c in hub.coordinators.values()] if hub else [],
    }
    return async_redact_data(result, TO_REDACT)


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: KlyqaPetConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for one device."""
    hub = getattr(entry, "runtime_data", None)
    if hub is None:
        return {"error": "entry_not_loaded"}
    for domain, device_id in device.identifiers:
        if domain == DOMAIN and (coordinator := hub.coordinators.get(device_id)) is not None:
            return async_redact_data(_coordinator_diagnostics(coordinator), TO_REDACT)
    return {"error": "device_not_found"}
