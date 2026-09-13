"""Tests for the light platform (air purifier LED and Strype strip)."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import color as color_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from pyklyqa_pet import StrypeState
from pyklyqa_pet.strype import StrypeDevice

from .conftest import setup_integration

ENTITY_ID = "light.klyqa_airpurifier_e85dfc_led"


@pytest.fixture
async def lights(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "lights")
async def test_light(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)
    state = hass.states.get(ENTITY_ID)
    assert state.state == "on"
    assert state.attributes[ATTR_RGB_COLOR] == (160, 40, 240)
    assert state.attributes[ATTR_BRIGHTNESS] == 204


@pytest.mark.usefixtures("lights")
async def test_light_commands(hass: HomeAssistant, mock_purifier: MagicMock) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_RGB_COLOR: (1, 2, 3)},
        blocking=True,
    )
    mock_purifier.set_led.assert_awaited_with(True, (1, 2, 3), None)
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    mock_purifier.set_led.assert_awaited_with(True, None, 50)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    mock_purifier.set_led.assert_awaited_with(True, None, None)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    mock_purifier.set_led.assert_awaited_with(False)


STRYPE_ENTITY_ID = "light.living_room_strip"


@pytest.mark.usefixtures("lights")
async def test_strype_light_reports_rgb_mode(hass: HomeAssistant) -> None:
    state = hass.states.get(STRYPE_ENTITY_ID)
    assert state.state == "on"
    assert state.attributes["color_mode"] == ColorMode.RGB
    assert state.attributes["rgb_color"] == (255, 128, 0)
    assert state.attributes["brightness"] == 178  # round(70 * 255 / 100) == round(178.5) == 178


async def test_strype_light_reports_color_temp_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    # The first poll for a Strype device fetches its length via read_length(), not
    # get_state(); patch both so the mode change is visible regardless of poll path.
    cct_state = replace(mock_strype.read_length.return_value, mode="cct")
    mock_strype.read_length = AsyncMock(return_value=cct_state)
    mock_strype.get_state = AsyncMock(return_value=cct_state)
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)
    state = hass.states.get(STRYPE_ENTITY_ID)
    assert state.attributes["color_mode"] == ColorMode.COLOR_TEMP
    assert state.attributes["color_temp_kelvin"] == 4000
    # Core derives the displayed rgb_color from the active color_temp_kelvin rather than
    # from the entity's own (stale, RGB-mode) rgb_color property, so it must not be the
    # raw device colour (255, 128, 0) from the fixture.
    expected_hs = color_util.color_temperature_to_hs(4000)
    expected_rgb = color_util.color_hs_to_RGB(*expected_hs)
    assert state.attributes["rgb_color"] == expected_rgb
    assert state.attributes["rgb_color"] != (255, 128, 0)


async def test_strype_light_reports_cmd_mode_as_rgb_fallback(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    cmd_state = replace(mock_strype.read_length.return_value, mode="cmd")
    mock_strype.read_length = AsyncMock(return_value=cmd_state)
    mock_strype.get_state = AsyncMock(return_value=cmd_state)
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)
    state = hass.states.get(STRYPE_ENTITY_ID)
    assert state.attributes["color_mode"] == ColorMode.RGB


@pytest.mark.usefixtures("lights")
async def test_strype_light_sets_colour_temperature(
    hass: HomeAssistant, mock_strype: MagicMock
) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": STRYPE_ENTITY_ID, "color_temp_kelvin": 3000},
        blocking=True,
    )
    mock_strype.set_state.assert_awaited_with(
        power_on=True,
        rgb=None,
        temperature_kelvin=3000,
        brightness_percent=None,
        transition_ms=None,
    )


@pytest.mark.usefixtures("lights")
async def test_strype_light_sets_brightness(hass: HomeAssistant, mock_strype: MagicMock) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": STRYPE_ENTITY_ID, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    mock_strype.set_state.assert_awaited_with(
        power_on=True,
        rgb=None,
        temperature_kelvin=None,
        brightness_percent=50,  # round(128 * 100 / 255)
        transition_ms=None,
    )


@pytest.mark.usefixtures("lights")
async def test_strype_light_turn_off_with_transition(
    hass: HomeAssistant, mock_strype: MagicMock
) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {"entity_id": STRYPE_ENTITY_ID, "transition": 2},
        blocking=True,
    )
    mock_strype.set_state.assert_awaited_with(power_on=False, transition_ms=2000)


@pytest.mark.usefixtures("lights")
async def test_strype_light_power_transition_reaches_the_device_as_a_temp_fade(
    hass: HomeAssistant, mock_strype: MagicMock
) -> None:
    """A transition that flips power must arrive as `temp_fade`, not `transitionTime` alone.

    The firmware overwrites its fade time with the stored fade-in/fade-out on any
    power flip unless the request carries `temp_fade`, so `transitionTime` alone is
    silently ignored for exactly the case Home Assistant asks for most. Driving the
    real library client (not the mock) is what makes the wire body observable here.
    """
    posted: list[dict] = []

    async def _record(method: str, path: str, body: dict | None = None) -> dict:
        posted.append(body or {})
        return {"status": "off", "mode": "rgb", "length_ret": 3}

    real = StrypeDevice(MagicMock(), "1.2.3.4", "tok")

    async def _through_the_real_client(**kwargs) -> StrypeState:
        return await real.set_state(**kwargs)

    with patch.object(StrypeDevice, "request", side_effect=_record):
        mock_strype.set_state.side_effect = _through_the_real_client
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {"entity_id": STRYPE_ENTITY_ID, "transition": 2},
            blocking=True,
        )
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {"entity_id": STRYPE_ENTITY_ID, "transition": 3},
            blocking=True,
        )

    assert posted[0]["temp_fade"] == {"out": 2000}
    assert posted[1]["temp_fade"] == {"in": 3000}
    assert all(body["type"] == "request" for body in posted)


async def test_strype_light_colour_write_in_cct_mode_converges_to_rgb(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    """Writing a colour while the device is in cct mode must flip the reported mode.

    The POST echo is partial, so the mode can only be trusted from the following
    GET; this asserts the entity converges on it instead of going stale.
    """
    cct_state = replace(mock_strype.get_state.return_value, mode="cct")
    mock_strype.read_length = AsyncMock(return_value=replace(cct_state, length_metres=3))
    mock_strype.get_state = AsyncMock(return_value=cct_state)
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get(STRYPE_ENTITY_ID).attributes["color_mode"] == ColorMode.COLOR_TEMP

    # The device switched to rgb; its POST echo carries only `color`, the GET both.
    rgb_state = replace(cct_state, mode="rgb", rgb=(10, 20, 30))
    mock_strype.get_state = AsyncMock(return_value=rgb_state)
    mock_strype.set_state = AsyncMock(
        return_value=StrypeState.from_dict(
            {"status": "on", "mode": "rgb", "color": {"red": 10, "green": 20, "blue": 30}}
        )
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": STRYPE_ENTITY_ID, ATTR_RGB_COLOR: (10, 20, 30)},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(STRYPE_ENTITY_ID)
    assert state.attributes["color_mode"] == ColorMode.RGB
    assert state.attributes["rgb_color"] == (10, 20, 30)


async def test_strype_light_temperature_write_in_rgb_mode_converges_to_cct(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    """The mirror case: a temperature write while the device is in rgb mode."""
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.LIGHT]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get(STRYPE_ENTITY_ID).attributes["color_mode"] == ColorMode.RGB

    cct_state = replace(mock_strype.get_state.return_value, mode="cct", temperature_kelvin=3000)
    mock_strype.get_state = AsyncMock(return_value=cct_state)
    mock_strype.set_state = AsyncMock(
        return_value=StrypeState.from_dict(
            {"status": "on", "mode": "cct", "temperature": 3000, "length_ret": 3}
        )
    )
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {"entity_id": STRYPE_ENTITY_ID, "color_temp_kelvin": 3000},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(STRYPE_ENTITY_ID)
    assert state.attributes["color_mode"] == ColorMode.COLOR_TEMP
    assert state.attributes["color_temp_kelvin"] == 3000
