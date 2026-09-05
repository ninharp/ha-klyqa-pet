"""Constants shared across the library."""

from enum import StrEnum
from typing import Final


class Environment(StrEnum):
    """Klyqa cloud environment."""

    TEST = "test"
    PROD = "prod"


class DeviceType(StrEnum):
    """Supported device families."""

    WELLY = "welly"
    FOODY = "foody"
    AIRPURIFIER = "airpurifier"


CLOUD_BASE_URLS: Final[dict[Environment, str]] = {
    Environment.TEST: "https://app-api.test.qconnex.io",
    Environment.PROD: "https://app-api.prod.qconnex.io",
}

DEFAULT_PORT: Final = 3333
API_PREFIX: Final = "/api/v1/"
DEV_ACCESS_TOKEN: Final = "aabbccddeeff0011223344"
ZEROCONF_TYPE: Final = "_qcxrest._tcp.local."
REQUEST_TIMEOUT: Final = 10
CLOUD_REQUEST_TIMEOUT: Final = 30

# The firmware allows at most 3 requests per 300 ms window per device; spacing our own
# requests keeps us under that even when another client (the Klyqa app, a second HA
# entry) is not also polling it.
MIN_REQUEST_INTERVAL: Final = 0.35
RATE_LIMIT_RETRY_DELAY: Final = 0.5
RATE_LIMIT_RETRIES: Final = 2
