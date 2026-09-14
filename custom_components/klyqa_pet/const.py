"""Constants for the Klyqa Pet integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "klyqa_pet"
MANUFACTURER: Final = "Klyqa"

# Config entry schema version. The minor version is bumped for backwards-compatible
# changes handled by async_migrate_entry; minor 2 made the cloud tenant part of a
# cloud entry's unique id ("<env>:<tenant>:<email>" instead of "<env>:<email>").
VERSION: Final = 1
MINOR_VERSION: Final = 2

# A local-only entry (devices added by IP + token, no cloud account) is recognised by
# entry.data[CONF_ENVIRONMENT] == ENVIRONMENT_LOCAL. It is not a value pyklyqa_pet's
# Environment enum knows about - it never reaches KlyqaCloudClient/Environment(...).
ENVIRONMENT_LOCAL: Final = "local"
# A config entry is a per-account singleton; a local entry is likewise a singleton per
# HA instance, so it always gets this fixed unique id.
LOCAL_ENTRY_UNIQUE_ID: Final = "local"

CONF_ENVIRONMENT: Final = "environment"
CONF_CLOUD_APP: Final = "cloud_app"
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
    Platform.TIME,
]

# The scan interval is user-configurable (options flow, CONF_SCAN_INTERVAL from
# homeassistant.const); this is the value used when an entry has no option stored yet.
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600
SYSTEM_INFO_INTERVAL: Final = timedelta(seconds=300)
# Settings (Welly/Foody) change far less often than state; fetch them only every 4th
# poll to reduce REST pressure on the device (2 min at the default 30 s scan interval,
# scaling with it), unless a settings write forces an earlier reload (see
# KlyqaDeviceCoordinator.mark_settings_stale).
SETTINGS_POLL_INTERVAL: Final = 4

# How long a device that still rejects its token after a cloud token recovery is left
# alone before another recovery is attempted for it.
TOKEN_RECOVERY_BACKOFF: Final = timedelta(minutes=15)
# How long a successful cloud token refresh is reused before another one is allowed, so
# several devices failing in the same poll cycle coalesce into a single cloud login.
TOKEN_REFRESH_COALESCE: Final = timedelta(seconds=60)

# Device value -> translation option key
WELLY_MODES: Final[dict[int, str]] = {
    0: "sensing",
    1: "fresh_water_24h",
    2: "water_change",
    3: "self_wash",
    4: "drain",
}
WELLY_PUMP_STATUS: Final[dict[int, str]] = {
    0: "normal",
    1: "low_water",
    2: "abnormal",
    3: "overweight",
    4: "no_clean_water",
}
WELLY_POWER_STATUS: Final[dict[int, str]] = {0: "off", 1: "on", 2: "power_saving"}
WELLY_POWER_SUPPLY: Final[dict[int, str]] = {0: "mains", 1: "battery"}

FOODY_FEEDING_STATE: Final[dict[int, str]] = {
    0: "idle",
    1: "dispensing",
    2: "pet_eating",
    3: "dispensing_wet_food",
}
FOODY_BOWL_STATE: Final[dict[int, str]] = {0: "normal", 1: "overweight", 2: "removed"}
FOODY_FOOD_BIN_STATE: Final[dict[int, str]] = {0: "low", 1: "sufficient"}
FOODY_ERROR_STATE: Final[dict[int, str]] = {
    0: "normal",
    1: "motor_stalled",
    2: "below_threshold",
    3: "motor_position_abnormal",
}
FOODY_MANUAL_REPORT: Final[dict[int, str]] = {
    0: "started",
    1: "succeeded",
    2: "failed",
    3: "failed_wet_food",
}
FOODY_SCHEDULED_REPORT: Final[dict[int, str]] = {
    0: "started",
    1: "succeeded",
    2: "failed",
    3: "slow_feed_updated",
    4: "terminated",
    5: "abnormal_fresh_food",
    6: "failed_wet_food",
}
FOODY_CUSTOM_BUTTON: Final[dict[int, str]] = {
    0: "none",
    1: "indicator_light",
    2: "alert_tone",
    3: "privacy_mode",
    4: "play_audio",
}
FOODY_BATTERY_MODE: Final[dict[int, str]] = {0: "standard", 1: "power_save"}
FOODY_CHARGING_PROTECTION: Final[dict[int, str]] = {1: "stop_charging", 2: "continue_charging"}

PURIFIER_AQI_GRADES: Final[dict[int, str]] = {
    0: "excellent",
    1: "good",
    2: "slightly_polluted",
    3: "heavily_polluted",
}
PURIFIER_RUN_MODES: Final[dict[int, str]] = {0: "standalone", 1: "auto", 2: "night", 3: "pet"}

STRYPE_LIGHT_MODES: Final = ("rgb", "cct", "cmd")
