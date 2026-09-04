import aiohttp
from aioresponses import aioresponses
import pytest

from pyklyqa_pet.cloud import CloudDevice, KlyqaCloudClient
from pyklyqa_pet.const import Environment
from pyklyqa_pet.exceptions import KlyqaAuthError, KlyqaConnectionError

LOGIN_URL = "https://app-api.test.qconnex.io/auth/login"
SETTINGS_URL = "https://app-api.test.qconnex.io/settings"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


async def test_login_success(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=201, payload={"accountToken": "acc-token"})
        client = KlyqaCloudClient(session, Environment.TEST)
        token = await client.login("user@example.com", "secret")
    assert token == "acc-token"
    assert client.account_token == "acc-token"


async def test_login_invalid_credentials(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=401, payload={"message": "Unauthorized"})
        client = KlyqaCloudClient(session, Environment.TEST)
        with pytest.raises(KlyqaAuthError):
            await client.login("user@example.com", "wrong")


async def test_login_connection_error(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, exception=aiohttp.ClientConnectionError("down"))
        client = KlyqaCloudClient(session, Environment.TEST)
        with pytest.raises(KlyqaConnectionError):
            await client.login("user@example.com", "secret")


async def test_login_missing_token_in_body(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=201, payload={})
        client = KlyqaCloudClient(session, Environment.TEST)
        with pytest.raises(KlyqaAuthError):
            await client.login("user@example.com", "secret")


async def test_list_devices(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=201, payload={"accountToken": "acc-token"})
        mocked.get(
            SETTINGS_URL,
            status=200,
            payload={
                "devices": [
                    {
                        "localDeviceId": "188b0eaf2d7c",
                        "accessToken": "dev-token-1",
                        "name": "Fountain",
                        "productId": "@klyqa.welly-dev",
                    },
                    {"localDeviceId": "A0F26219DC34", "accessToken": "dev-token-2"},
                    {"accessToken": "no-id"},
                ]
            },
        )
        client = KlyqaCloudClient(session, Environment.TEST)
        await client.login("user@example.com", "secret")
        devices = await client.list_devices()
        request_headers = list(mocked.requests.values())[1][0].kwargs["headers"]
    assert request_headers["Authorization"] == "Bearer acc-token"
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


async def test_list_devices_expired_token(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=201, payload={"accountToken": "acc-token"})
        mocked.get(SETTINGS_URL, status=401)
        client = KlyqaCloudClient(session, Environment.TEST)
        await client.login("user@example.com", "secret")
        with pytest.raises(KlyqaAuthError):
            await client.list_devices()


async def test_prod_base_url(session: aiohttp.ClientSession) -> None:
    with aioresponses() as mocked:
        mocked.post(
            "https://app-api.prod.qconnex.io/auth/login",
            status=201,
            payload={"accountToken": "t"},
        )
        client = KlyqaCloudClient(session, Environment.PROD)
        assert await client.login("u", "p") == "t"
