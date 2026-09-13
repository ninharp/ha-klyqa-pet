"""Async client library for Klyqa pet devices."""

from __future__ import annotations

import aiohttp

from .airpurifier import AirPurifierDevice, AirPurifierRunMode, AirPurifierState
from .cloud import CloudDevice, KlyqaCloudClient
from .const import (
    DEFAULT_PORT,
    DEV_ACCESS_TOKEN,
    ZEROCONF_TYPE,
    CloudApp,
    DeviceType,
    Environment,
)
from .device import KlyqaDevice, SystemInfo
from .discovery import DiscoveredDevice, device_type_from_product_id, parse_zeroconf_properties
from .exceptions import (
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDeviceError,
    KlyqaError,
    KlyqaRateLimitError,
)
from .foody import FoodyDevice, FoodySettings, FoodyState
from .strype import StrypeDevice, StrypeState
from .welly import WellyDevice, WellyMode, WellySettings, WellyState

__version__ = "0.1.5"

_DEVICE_CLASSES: dict[DeviceType, type[KlyqaDevice]] = {
    DeviceType.WELLY: WellyDevice,
    DeviceType.FOODY: FoodyDevice,
    DeviceType.AIRPURIFIER: AirPurifierDevice,
    DeviceType.STRYPE: StrypeDevice,
}


def create_device(
    device_type: DeviceType,
    session: aiohttp.ClientSession,
    host: str,
    access_token: str,
    port: int = DEFAULT_PORT,
) -> KlyqaDevice:
    """Instantiate the device client class matching the device type."""
    return _DEVICE_CLASSES[device_type](session, host, access_token, port)


__all__ = [
    "DEFAULT_PORT",
    "DEV_ACCESS_TOKEN",
    "ZEROCONF_TYPE",
    "AirPurifierDevice",
    "AirPurifierRunMode",
    "AirPurifierState",
    "CloudApp",
    "CloudDevice",
    "DeviceType",
    "DiscoveredDevice",
    "Environment",
    "FoodyDevice",
    "FoodySettings",
    "FoodyState",
    "KlyqaAuthError",
    "KlyqaCloudClient",
    "KlyqaConnectionError",
    "KlyqaDevice",
    "KlyqaDeviceError",
    "KlyqaError",
    "KlyqaRateLimitError",
    "StrypeDevice",
    "StrypeState",
    "SystemInfo",
    "WellyDevice",
    "WellyMode",
    "WellySettings",
    "WellyState",
    "create_device",
    "device_type_from_product_id",
    "parse_zeroconf_properties",
]
