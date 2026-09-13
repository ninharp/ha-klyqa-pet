import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.strype import StrypeDevice, StrypeState

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
STATE = "/api/v1/device/state"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> StrypeDevice:
    return StrypeDevice(session, api.host, "tok", api.port)


def test_state_from_dict() -> None:
    state = StrypeState.from_dict(load_fixture("strype_state.json"))
    assert state.power_on is True
    assert state.mode == "rgb"
    assert state.rgb == (255, 128, 0)
    assert state.temperature_kelvin == 4000
    assert state.brightness_percent == 70
    assert state.length_metres is None


def test_state_from_dict_reads_length_from_post_response() -> None:
    payload = load_fixture("strype_state.json") | {"length_ret": 3}
    assert StrypeState.from_dict(payload).length_metres == 3


def test_state_from_dict_tolerates_missing_keys() -> None:
    state = StrypeState.from_dict({})
    assert state.power_on is False
    assert state.mode == "rgb"
    assert state.rgb == (0, 0, 0)
    assert state.length_metres is None


async def test_get_state(device: StrypeDevice, api: FakeApi) -> None:
    api.add("GET", STATE, 200, load_fixture("strype_state.json"))
    assert (await device.get_state()).brightness_percent == 70


async def test_set_state_sends_only_given_fields(device: StrypeDevice, api: FakeApi) -> None:
    api.add("POST", STATE, 200, load_fixture("strype_state.json") | {"length_ret": 2})
    state = await device.set_state(power_on=True, rgb=(10, 20, 30), transition_ms=800)
    assert api.last_call().json == {
        "status": "on",
        "color": {"red": 10, "green": 20, "blue": 30},
        "transitionTime": 800,
    }
    assert state.length_metres == 2


async def test_set_state_temperature_and_brightness(device: StrypeDevice, api: FakeApi) -> None:
    api.add("POST", STATE, 200, load_fixture("strype_state.json"))
    await device.set_state(temperature_kelvin=3000, brightness_percent=42)
    assert api.last_call().json == {"temperature": 3000, "brightness": {"percentage": 42}}


async def test_detect_length(device: StrypeDevice, api: FakeApi) -> None:
    api.add("POST", STATE, 200, load_fixture("strype_state.json") | {"length_ret": 5})
    state = await device.detect_length()
    assert api.last_call().json == {"length_detection": 1}
    assert state.length_metres == 5


async def test_read_length_posts_an_empty_body(device: StrypeDevice, api: FakeApi) -> None:
    api.add("POST", STATE, 200, load_fixture("strype_state.json") | {"length_ret": 1})
    state = await device.read_length()
    assert api.last_call().json == {}
    assert state.length_metres == 1
