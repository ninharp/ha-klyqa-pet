"""mDNS discovery helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .const import DEFAULT_PORT, DeviceType

_PRODUCT_ID_MAP: dict[str, DeviceType] = {
    "@klyqa.welly": DeviceType.WELLY,
    "@klyqa.welly-dev": DeviceType.WELLY,
    "@pfriendly.water-fountain": DeviceType.WELLY,
    "@pfriendly.water-fountain-dev": DeviceType.WELLY,
    "@klyqa.foody": DeviceType.FOODY,
    "@klyqa.foody-dev": DeviceType.FOODY,
    "@pfriendly.foody": DeviceType.FOODY,
    "@pfriendly.foody-dev": DeviceType.FOODY,
    "@klyqa.airpurifier2": DeviceType.AIRPURIFIER,
    "@klyqa.airpurifier2-dev": DeviceType.AIRPURIFIER,
    "@pfriendly.airpurifier": DeviceType.AIRPURIFIER,
    "@pfriendly.airpurifier-dev": DeviceType.AIRPURIFIER,
}


def device_type_from_product_id(product_id: str) -> DeviceType | None:
    """Return the device family for a QConnex product id, or None if unsupported."""
    return _PRODUCT_ID_MAP.get(product_id)


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """A supported device announced via mDNS."""

    host: str
    port: int
    product_id: str
    local_device_id: str
    product_name: str
    device_name: str
    device_type: DeviceType


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def parse_zeroconf_properties(
    host: str,
    port: int | None,
    properties: Mapping[str | bytes, str | bytes | None],
) -> DiscoveredDevice | None:
    """Build a DiscoveredDevice from mDNS TXT records; None if not a supported device."""
    decoded = {_decode(key): _decode(value) for key, value in properties.items()}
    product_id = decoded.get("productId", "")
    device_type = device_type_from_product_id(product_id)
    local_device_id = decoded.get("localDeviceId", "").upper()
    if device_type is None or not local_device_id:
        return None
    return DiscoveredDevice(
        host=host,
        port=port or DEFAULT_PORT,
        product_id=product_id,
        local_device_id=local_device_id,
        product_name=decoded.get("productName", ""),
        device_name=decoded.get("deviceName", ""),
        device_type=device_type,
    )
