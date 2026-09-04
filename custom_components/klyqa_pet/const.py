"""Constants for the Klyqa Pet integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "klyqa_pet"
MANUFACTURER: Final = "Klyqa"

CONF_ENVIRONMENT: Final = "environment"
CONF_DEVICES: Final = "devices"
CONF_MANUAL_DEVICES: Final = "manual_devices"
CONF_LOCAL_DEVICE_ID: Final = "local_device_id"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_PRODUCT_ID: Final = "product_id"
CONF_PRODUCT_NAME: Final = "product_name"
CONF_DEVICE_NAME: Final = "device_name"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.FAN,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

SCAN_INTERVAL: Final = timedelta(seconds=15)
SYSTEM_INFO_INTERVAL: Final = timedelta(seconds=300)
