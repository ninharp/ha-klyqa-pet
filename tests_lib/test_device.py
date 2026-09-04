import json
from pathlib import Path

import aiohttp
from aioresponses import aioresponses
import pytest

from pyklyqa_pet.device import KlyqaDevice, SystemInfo
from pyklyqa_pet.exceptions import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://192.168.2.148:3333/api/v1/"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def device(session: aiohttp.ClientSession) -> KlyqaDevice:
    return KlyqaDevice(session, "192.168.2.148", "tok")


async def test_base_url_and_setters(device: KlyqaDevice) -> None:
    assert device.base_url == BASE
    device.host = "10.0.0.1"
    device.access_token = "new"
    assert device.base_url == "http://10.0.0.1:3333/api/v1/"
    assert device.access_token == "new"


async def test_get_system_info(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}system/info", payload=load_fixture("system_info.json"))
        info = await device.get_system_info()
        headers = next(iter(mocked.requests.values()))[0].kwargs["headers"]
    assert headers["Authorization"] == "tok"
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


async def test_reboot(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}system/command", payload={"type": "success"})
        await device.reboot()
        call = next(iter(mocked.requests.values()))[0]
    assert call.kwargs["json"] == {"command": {"type": "reboot"}}


async def test_unauthorized(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(
            f"{BASE}system/info",
            status=401,
            payload={"type": "error", "error": ["Unauthorized"]},
        )
        with pytest.raises(KlyqaAuthError):
            await device.get_system_info()


async def test_device_error_body(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}system/command", payload={"type": "error", "error": ["bad command"]})
        with pytest.raises(KlyqaDeviceError) as excinfo:
            await device.reboot()
    assert excinfo.value.errors == ["bad command"]


async def test_connection_error(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}system/info", exception=aiohttp.ClientConnectionError("nope"))
        with pytest.raises(KlyqaConnectionError):
            await device.get_system_info()


async def test_timeout(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}system/info", exception=TimeoutError())
        with pytest.raises(KlyqaConnectionError):
            await device.get_system_info()


async def test_http_500(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}system/info", status=500, body="boom")
        with pytest.raises(KlyqaConnectionError):
            await device.get_system_info()


async def test_non_json_body(device: KlyqaDevice) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}system/info", status=200, body="<html>")
        with pytest.raises(KlyqaConnectionError):
            await device.get_system_info()
