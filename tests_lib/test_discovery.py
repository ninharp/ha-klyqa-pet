import pytest

from pyklyqa_pet.const import DeviceType
from pyklyqa_pet.discovery import (
    DiscoveredDevice,
    device_type_from_product_id,
    parse_zeroconf_properties,
)


@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        ("@klyqa.welly", DeviceType.WELLY),
        ("@klyqa.welly-dev", DeviceType.WELLY),
        ("@pfriendly.water-fountain", DeviceType.WELLY),
        ("@klyqa.foody", DeviceType.FOODY),
        ("@klyqa.foody-dev", DeviceType.FOODY),
        ("@pfriendly.foody-dev", DeviceType.FOODY),
        ("@klyqa.airpurifier2", DeviceType.AIRPURIFIER),
        ("@klyqa.airpurifier2-dev", DeviceType.AIRPURIFIER),
        ("@klyqa.cleaning.airpurifier1", DeviceType.AIRPURIFIER),
        ("@pfriendly.airpurifier", DeviceType.AIRPURIFIER),
        ("@klyqa.lighting.kl-rgbc3.rgbcw", None),
        ("", None),
    ],
)
def test_device_type_from_product_id(product_id: str, expected: DeviceType | None) -> None:
    assert device_type_from_product_id(product_id) is expected


def test_parse_zeroconf_properties_bytes() -> None:
    props = {
        b"productId": b"@klyqa.welly-dev",
        b"localDeviceId": b"188B0EAF2D7C",
        b"productName": b"Klyqa Welly",
        b"deviceName": b"Kitchen fountain",
        b"state": b"NA",
        b"path": b"/api/v1/",
    }
    result = parse_zeroconf_properties("192.168.2.148", 3333, props)
    assert result == DiscoveredDevice(
        host="192.168.2.148",
        port=3333,
        product_id="@klyqa.welly-dev",
        local_device_id="188B0EAF2D7C",
        product_name="Klyqa Welly",
        device_name="Kitchen fountain",
        device_type=DeviceType.WELLY,
    )


def test_parse_zeroconf_properties_str_and_default_port() -> None:
    props = {"productId": "@klyqa.foody", "localDeviceId": "a0f26219dc34"}
    result = parse_zeroconf_properties("10.0.0.5", None, props)
    assert result is not None
    assert result.port == 3333
    assert result.local_device_id == "A0F26219DC34"
    assert result.product_name == ""
    assert result.device_type is DeviceType.FOODY


def test_parse_zeroconf_properties_unknown_product() -> None:
    props = {"productId": "@klyqa.lighting.kl-rgbc3.rgbcw", "localDeviceId": "80659988019C"}
    assert parse_zeroconf_properties("10.0.0.6", 3333, props) is None


def test_parse_zeroconf_properties_missing_device_id() -> None:
    assert parse_zeroconf_properties("10.0.0.6", 3333, {"productId": "@klyqa.welly"}) is None
