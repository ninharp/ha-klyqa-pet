"""Config flow for Klyqa Pet (placeholder, fully implemented in a later task)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class KlyqaPetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Klyqa Pet."""

    VERSION = 1

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication after the cloud rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to sign in again."""
        return self.async_show_form(step_id="reauth_confirm")
