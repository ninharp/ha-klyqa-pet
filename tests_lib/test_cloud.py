import aiohttp
import pytest

from pyklyqa_pet.cloud import CloudDevice, KlyqaCloudClient
from pyklyqa_pet.const import CLOUD_BASE_URLS, Environment
from pyklyqa_pet.exceptions import KlyqaAuthError, KlyqaConnectionError

from .conftest import FakeApi


def make_client(session: aiohttp.ClientSession, api: FakeApi) -> KlyqaCloudClient:
    return KlyqaCloudClient(session, Environment.TEST, base_url=api.base_url)


def test_base_urls() -> None:
    assert CLOUD_BASE_URLS[Environment.TEST] == "https://app-api.test.qconnex.io"
    assert CLOUD_BASE_URLS[Environment.PROD] == "https://app-api.prod.qconnex.io"


async def test_login_success(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 201, {"accountToken": "acc-token"})
    client = make_client(session, api)
    token = await client.login("user@example.com", "secret")
    assert token == "acc-token"
    assert client.account_token == "acc-token"
    assert api.last_call().json == {"email": "user@example.com", "password": "secret"}


async def test_login_invalid_credentials(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 401, {"message": "Unauthorized"})
    with pytest.raises(KlyqaAuthError):
        await make_client(session, api).login("user@example.com", "wrong")


async def test_login_connection_error(session: aiohttp.ClientSession) -> None:
    client = KlyqaCloudClient(session, Environment.TEST, base_url="http://127.0.0.1:1")
    with pytest.raises(KlyqaConnectionError):
        await client.login("user@example.com", "secret")


async def test_login_server_error(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 500, body="boom")
    with pytest.raises(KlyqaConnectionError):
        await make_client(session, api).login("user@example.com", "secret")


async def test_login_missing_token_in_body(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 201, {})
    with pytest.raises(KlyqaAuthError):
        await make_client(session, api).login("user@example.com", "secret")


async def test_list_devices(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 201, {"accountToken": "acc-token"})
    api.add(
        "GET",
        "/settings",
        200,
        {
            "devices": [
                {
                    "localDeviceId": "188b0eaf2d7c",
                    "accessToken": "dev-token-1",
                    "name": "Fountain",
                    "productId": "@klyqa.welly-dev",
                },
                {"localDeviceId": "A0F26219DC34", "accessToken": "dev-token-2"},
                {"accessToken": "no-id"},
                "not-a-dict",
            ]
        },
    )
    client = make_client(session, api)
    await client.login("user@example.com", "secret")
    devices = await client.list_devices()
    assert api.last_call().headers["Authorization"] == "Bearer acc-token"
    assert devices == [
        CloudDevice(
            local_device_id="188B0EAF2D7C",
            access_token="dev-token-1",
            name="Fountain",
            product_id="@klyqa.welly-dev",
            raw=devices[0].raw,
        ),
        CloudDevice(
            local_device_id="A0F26219DC34",
            access_token="dev-token-2",
            name="",
            product_id="",
            raw=devices[1].raw,
        ),
    ]


async def test_list_devices_without_login(session: aiohttp.ClientSession) -> None:
    client = KlyqaCloudClient(session, Environment.PROD)
    with pytest.raises(KlyqaAuthError):
        await client.list_devices()


async def test_list_devices_expired_token(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 201, {"accountToken": "acc-token"})
    api.add("GET", "/settings", 401)
    client = make_client(session, api)
    await client.login("user@example.com", "secret")
    with pytest.raises(KlyqaAuthError):
        await client.list_devices()


async def test_list_devices_server_error(session: aiohttp.ClientSession, api: FakeApi) -> None:
    api.add("POST", "/auth/login", 201, {"accountToken": "acc-token"})
    api.add("GET", "/settings", 503, body="down")
    client = make_client(session, api)
    await client.login("user@example.com", "secret")
    with pytest.raises(KlyqaConnectionError):
        await client.list_devices()
