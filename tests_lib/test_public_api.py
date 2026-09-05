import aiohttp
import pytest

import pyklyqa_pet
from pyklyqa_pet import AirPurifierDevice, DeviceType, FoodyDevice, WellyDevice, create_device


@pytest.mark.parametrize(
    ("device_type", "expected_cls"),
    [
        (DeviceType.WELLY, WellyDevice),
        (DeviceType.FOODY, FoodyDevice),
        (DeviceType.AIRPURIFIER, AirPurifierDevice),
    ],
)
async def test_create_device(device_type: DeviceType, expected_cls: type) -> None:
    async with aiohttp.ClientSession() as session:
        device = create_device(device_type, session, "10.0.0.1", "tok", port=3334)
    assert isinstance(device, expected_cls)
    assert device.port == 3334


def test_public_names() -> None:
    for name in (
        "Environment",
        "KlyqaCloudClient",
        "KlyqaDevice",
        "SystemInfo",
        "WellyState",
        "FoodyState",
        "AirPurifierState",
        "KlyqaAuthError",
        "parse_zeroconf_properties",
    ):
        assert hasattr(pyklyqa_pet, name)
