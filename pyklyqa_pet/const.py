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
