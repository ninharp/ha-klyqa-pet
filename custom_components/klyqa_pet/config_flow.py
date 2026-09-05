"""Config and options flow for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
from typing import Any, cast

from homeassistant.config_entries import (
    SOURCE_ZEROCONF,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from pyklyqa_pet import (
    DEFAULT_PORT,
    DiscoveredDevice,
    Environment,
    KlyqaAuthError,
    KlyqaConnectionError,
    KlyqaDevice,
    KlyqaDeviceError,
    device_type_from_product_id,
    parse_zeroconf_properties,
)

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_ENVIRONMENT,
    CONF_MANUAL_DEVICES,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    DOMAIN,
    ENVIRONMENT_LOCAL,
    LOCAL_ENTRY_UNIQUE_ID,
)
from .hub import (
    DeviceRecord,
    async_fetch_cloud_devices,
    async_release_device_from_other_entries,
    merge_device_records,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENVIRONMENT, default=Environment.PROD.value): SelectSelector(
            SelectSelectorConfig(
                options=[env.value for env in Environment],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_ENVIRONMENT,
            )
        ),
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR})
STEP_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_ACCESS_TOKEN): PASSWORD_SELECTOR,
    }
)


def _account_unique_id(environment: str, email: str) -> str:
    return f"{environment}:{email.strip().lower()}"


class KlyqaPetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the account-based config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._discovered: DiscoveredDevice | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> KlyqaPetOptionsFlow:
        """Return the options flow."""
        return KlyqaPetOptionsFlow()

    async def _async_try_login(
        self, environment: str, email: str, password: str, errors: dict[str, str]
    ) -> dict[str, DeviceRecord] | None:
        """Log in and return the device records, filling errors on failure."""
        try:
            return await async_fetch_cloud_devices(self.hass, environment, email, password)
        except KlyqaAuthError:
            errors["base"] = "invalid_auth"
        except KlyqaConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while talking to the Klyqa cloud")
            errors["base"] = "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user choose between a cloud account and a local-only device."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", "local"])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for environment and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = await self._async_try_login(
                user_input[CONF_ENVIRONMENT],
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                errors,
            )
            if devices is not None:
                await self.async_set_unique_id(
                    _account_unique_id(user_input[CONF_ENVIRONMENT], user_input[CONF_EMAIL]),
                    raise_on_progress=False,
                )
                self._abort_if_unique_id_configured()
                self._async_abort_stale_discoveries(devices)
                return self.async_create_entry(
                    title=f"{user_input[CONF_EMAIL]} ({user_input[CONF_ENVIRONMENT]})",
                    data={
                        CONF_ENVIRONMENT: user_input[CONF_ENVIRONMENT],
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_DEVICES: devices,
                    },
                )
        return self.async_show_form(
            step_id="cloud",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )

    def _existing_local_entry(self) -> ConfigEntry | None:
        """Return the single local-only entry, if one exists."""
        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id == LOCAL_ENTRY_UNIQUE_ID:
                return entry
        return None

    async def async_step_local(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add a device by IP and access token, without any cloud account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            token = user_input[CONF_ACCESS_TOKEN]
            device = KlyqaDevice(async_get_clientsession(self.hass), host, token, port)
            try:
                info = await device.get_system_info()
            except KlyqaAuthError:
                errors["base"] = "invalid_auth"
            except (KlyqaConnectionError, KlyqaDeviceError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while adding a local device")
                errors["base"] = "unknown"
            else:
                if device_type_from_product_id(info.product_id) is None:
                    errors["base"] = "not_supported"
                else:
                    record = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_ACCESS_TOKEN: token,
                        CONF_PRODUCT_ID: info.product_id,
                        CONF_PRODUCT_NAME: info.product_name,
                        CONF_DEVICE_NAME: "",
                    }
                    await self.async_set_unique_id(LOCAL_ENTRY_UNIQUE_ID, raise_on_progress=False)
                    self._async_abort_stale_discoveries([info.device_id])
                    existing = self._existing_local_entry()
                    # A device now claimed here must be released from every account entry
                    # that still lists it as a cloud record - a device is owned by exactly
                    # one entry. The entry being created/updated here is excluded by id (it
                    # does not exist yet on the create path, so nothing to exclude there).
                    await async_release_device_from_other_entries(
                        self.hass,
                        info.device_id,
                        except_entry_id=existing.entry_id if existing is not None else "",
                    )
                    if existing is not None:
                        manual = {
                            **existing.options.get(CONF_MANUAL_DEVICES, {}),
                            info.device_id: record,
                        }
                        self.hass.config_entries.async_update_entry(
                            existing,
                            options={**existing.options, CONF_MANUAL_DEVICES: manual},
                        )
                        self.hass.config_entries.async_schedule_reload(existing.entry_id)
                        return self.async_abort(reason="device_added")
                    return self.async_create_entry(
                        title="Klyqa Pet (local)",
                        data={CONF_ENVIRONMENT: ENVIRONMENT_LOCAL, CONF_DEVICES: {}},
                        options={CONF_MANUAL_DEVICES: {info.device_id: record}},
                    )
        suggested = user_input
        if suggested is None and self._discovered is not None:
            suggested = {CONF_HOST: self._discovered.host, CONF_PORT: self._discovered.port}
        return self.async_show_form(
            step_id="local",
            data_schema=self.add_suggested_values_to_schema(STEP_MANUAL_SCHEMA, suggested),
            errors=errors,
        )

    def _is_device_configured(self, device_id: str) -> bool:
        """Return True if any current entry already has this device."""
        return any(
            device_id in entry.data.get(CONF_DEVICES, {})
            or device_id in entry.options.get(CONF_MANUAL_DEVICES, {})
            for entry in self._async_current_entries(include_ignore=False)
        )

    def _async_abort_stale_discoveries(self, device_ids: Iterable[str]) -> None:
        """Abort other devices' discovery flows once those devices got configured.

        Each mDNS-discovered device starts its own discovery flow. When one of them is
        completed with a cloud account (or a device is added manually), the resulting
        entry can end up owning several devices at once - every other discovery flow
        for those devices must be aborted, or it stays listed as a stale "Discovered"
        card that only aborts once clicked.
        """
        unique_ids = {f"discovered:{device_id}" for device_id in device_ids}
        for flow in self._async_in_progress(include_uninitialized=True):
            context = flow["context"]
            if context.get("source") == SOURCE_ZEROCONF and context.get("unique_id") in unique_ids:
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle a device announced via mDNS."""
        discovered = parse_zeroconf_properties(
            discovery_info.host,
            discovery_info.port,
            cast(Mapping[str | bytes, str | bytes | None], discovery_info.properties),
        )
        if discovered is None:
            return self.async_abort(reason="not_supported")
        if self._is_device_configured(discovered.local_device_id):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(f"discovered:{discovered.local_device_id}")
        self._discovered = discovered
        self.context["title_placeholders"] = {
            "product": discovered.product_name or discovered.product_id,
            "name": discovered.device_name or discovered.local_device_id,
        }
        return await self.async_step_discovery_confirm()

    @staticmethod
    def _discovered_name(discovered: DiscoveredDevice) -> str:
        return discovered.device_name or discovered.product_name or discovered.local_device_id

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose how to set up the discovered device."""
        assert self._discovered is not None
        if user_input is None and self._is_device_configured(self._discovered.local_device_id):
            # The device was configured elsewhere while this card sat unattended (e.g.
            # another discovery flow was completed with the same cloud account); never
            # show the login menu again for it.
            return self.async_abort(reason="already_configured")
        return self.async_show_menu(
            step_id="discovery_confirm",
            menu_options=["cloud", "local"],
            description_placeholders={
                "name": self._discovered_name(self._discovered),
                "host": self._discovered.host,
                "product": self._discovered.product_name or self._discovered.product_id,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the cloud rejected the credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        if entry.data.get(CONF_ENVIRONMENT) == ENVIRONMENT_LOCAL:
            # A local entry has no cloud account and is never put into reauth by the
            # hub, but guard here too in case something else triggers it.
            return self.async_abort(reason="not_supported_local")
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = await self._async_try_login(
                entry.data[CONF_ENVIRONMENT],
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                errors,
            )
            if devices is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_DEVICES: merge_device_records(
                            entry.data.get(CONF_DEVICES, {}), devices
                        ),
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the password of the same account."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_ENVIRONMENT) == ENVIRONMENT_LOCAL:
            return self.async_abort(reason="not_supported_local")
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = await self._async_try_login(
                entry.data[CONF_ENVIRONMENT],
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                errors,
            )
            if devices is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_DEVICES: merge_device_records(
                            entry.data.get(CONF_DEVICES, {}), devices
                        ),
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )


class KlyqaPetOptionsFlow(OptionsFlowWithReload):
    """Options flow: add a device manually by host and access token."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate the device and store it in the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            token = user_input[CONF_ACCESS_TOKEN]
            device = KlyqaDevice(async_get_clientsession(self.hass), host, token, port)
            try:
                info = await device.get_system_info()
            except KlyqaAuthError:
                errors["base"] = "invalid_auth"
            except (KlyqaConnectionError, KlyqaDeviceError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while adding a manual device")
                errors["base"] = "unknown"
            else:
                if device_type_from_product_id(info.product_id) is None:
                    errors["base"] = "not_supported"
                else:
                    manual = dict(self.config_entry.options.get(CONF_MANUAL_DEVICES, {}))
                    manual[info.device_id] = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_ACCESS_TOKEN: token,
                        CONF_PRODUCT_ID: info.product_id,
                        CONF_PRODUCT_NAME: info.product_name,
                        CONF_DEVICE_NAME: "",
                    }
                    # A device is owned by exactly one entry: claiming it here (this
                    # entry, which is `OptionsFlowWithReload` and thus reloads itself)
                    # must release it from every other loaded entry that still lists it
                    # as a cloud record.
                    await async_release_device_from_other_entries(
                        self.hass, info.device_id, except_entry_id=self.config_entry.entry_id
                    )
                    return self.async_create_entry(
                        data={**self.config_entry.options, CONF_MANUAL_DEVICES: manual}
                    )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(STEP_MANUAL_SCHEMA, user_input),
            errors=errors,
        )
