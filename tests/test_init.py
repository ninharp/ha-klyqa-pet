"""Tests for integration loading."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.klyqa_pet.const import DOMAIN


async def test_integration_is_loadable(hass: HomeAssistant) -> None:
    """The klyqa_pet custom integration can be resolved by Home Assistant."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN
    assert integration.integration_type == "hub"
