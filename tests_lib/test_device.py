import json
from pathlib import Path

import aiohttp
import pytest

import pyklyqa_pet.device
from pyklyqa_pet.device import KlyqaDevice, SystemInfo
from pyklyqa_pet.exceptions import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> KlyqaDevice:
    return KlyqaDevice(session, api.host, "tok", api.port)


async def test_base_url_and_setters(session: aiohttp.ClientSession) -> None:
    device = KlyqaDevice(session, "192.168.2.148", "tok")
    assert device.base_url == "http://192.168.2.148:3333/api/v1/"
    device.host = "10.0.0.1"
    device.access_token = "new"
    assert device.base_url == "http://10.0.0.1:3333/api/v1/"
    assert device.access_token == "new"
    assert device.port == 3333


async def test_get_system_info(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("GET", "/api/v1/system/info", 200, load_fixture("system_info.json"))
    info = await device.get_system_info()
    assert api.last_call().headers["Authorization"] == "tok"
    assert info == SystemInfo(
        product_id="@klyqa.welly-dev",
        device_id="188B0EAF2D7C",
        product_name="Klyqa Welly",
        service_name="KLYQA-AF2D7C",
        serial_number=4711,
        hw_revision=2,
        sdk_version="2.3.0",
        app_version="1.4.2",
        build_date="Aug 24 2026 13:30:00",
        boot_reason=1,
        boot_time=1756990000,
        partition="ota_0",
        free_heap=123456,
        chip_model="esp32c3",
        raw=info.raw,
    )


async def test_reboot(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("PUT", "/api/v1/system/command", 200, {"type": "success"})
    await device.reboot()
    assert api.last_call().json == {"command": {"type": "reboot"}}


async def test_unauthorized(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("GET", "/api/v1/system/info", 401, {"type": "error", "error": ["Unauthorized"]})
    with pytest.raises(KlyqaAuthError):
        await device.get_system_info()


async def test_device_error_body(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("PUT", "/api/v1/system/command", 200, {"type": "error", "error": ["bad command"]})
    with pytest.raises(KlyqaDeviceError) as excinfo:
        await device.reboot()
    assert excinfo.value.errors == ["bad command"]


async def test_device_error_with_string_error(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("PUT", "/api/v1/system/command", 200, {"type": "error", "error": "single"})
    with pytest.raises(KlyqaDeviceError) as excinfo:
        await device.reboot()
    assert excinfo.value.errors == ["single"]


async def test_connection_error(session: aiohttp.ClientSession) -> None:
    device = KlyqaDevice(session, "127.0.0.1", "tok", 1)
    with pytest.raises(KlyqaConnectionError):
        await device.get_system_info()


async def test_timeout(device: KlyqaDevice, api: FakeApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pyklyqa_pet.device, "REQUEST_TIMEOUT", 0.05)
    api.add("GET", "/api/v1/system/info", 200, {"type": "system_info"}, delay=0.5)
    with pytest.raises(KlyqaConnectionError):
        await device.get_system_info()


async def test_http_500(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("GET", "/api/v1/system/info", 500, body="boom")
    with pytest.raises(KlyqaConnectionError):
        await device.get_system_info()


async def test_non_json_body(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("GET", "/api/v1/system/info", 200, body="<html>")
    with pytest.raises(KlyqaConnectionError):
        await device.get_system_info()


async def test_json_not_an_object(device: KlyqaDevice, api: FakeApi) -> None:
    api.add("GET", "/api/v1/system/info", 200, [1, 2])
    with pytest.raises(KlyqaConnectionError):
        await device.get_system_info()
