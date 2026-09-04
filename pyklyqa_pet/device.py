"""Base client for the local QConnex REST API."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

import aiohttp

from .const import API_PREFIX, DEFAULT_PORT, REQUEST_TIMEOUT
from .exceptions import KlyqaAuthError, KlyqaConnectionError, KlyqaDeviceError

_LOGGER = logging.getLogger(__name__)


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a JSON value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    """Coerce a JSON value (bool, 0/1, "on"/"off") to bool."""
    if isinstance(value, str):
        return value.lower() in ("on", "true", "1")
    return bool(value)


def _as_str(value: Any) -> str:
    """Coerce a JSON value to str, None becomes ''."""
    return "" if value is None else str(value)


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """Response of GET system/info."""

    product_id: str
    device_id: str
    product_name: str
    service_name: str
    serial_number: int
    hw_revision: int
    sdk_version: str
    app_version: str
    build_date: str
    boot_reason: int
    boot_time: int
    partition: str
    free_heap: int
    chip_model: str
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemInfo:
        """Parse the system info JSON object."""
        chip = data.get("chip_info") or {}
        return cls(
            product_id=_as_str(data.get("product_id")),
            device_id=_as_str(data.get("device_id")).upper(),
            product_name=_as_str(data.get("product_name")),
            service_name=_as_str(data.get("service_name")),
            serial_number=_as_int(data.get("serial_number")),
            hw_revision=_as_int(data.get("hw_revision")),
            sdk_version=_as_str(data.get("sdk_ver")),
            app_version=_as_str(data.get("app_ver")),
            build_date=_as_str(data.get("build_date")),
            boot_reason=_as_int(data.get("boot_reason")),
            boot_time=_as_int(data.get("boot")),
            partition=_as_str(data.get("partition")),
            free_heap=_as_int(data.get("free_heap")),
            chip_model=_as_str(chip.get("model")) if isinstance(chip, dict) else "",
            raw=data,
        )


class KlyqaDevice:
    """Generic QConnex device: shared endpoints and request plumbing."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        access_token: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Create a device client bound to host:port with the given access token."""
        self._session = session
        self._host = host
        self._port = port
        self._access_token = access_token

    @property
    def host(self) -> str:
        """Return the current host/IP."""
        return self._host

    @host.setter
    def host(self, value: str) -> None:
        self._host = value

    @property
    def port(self) -> int:
        """Return the REST port."""
        return self._port

    @property
    def access_token(self) -> str:
        """Return the access token used for the Authorization header."""
        return self._access_token

    @access_token.setter
    def access_token(self, value: str) -> None:
        self._access_token = value

    @property
    def base_url(self) -> str:
        """Return the API base URL including the /api/v1/ prefix."""
        return f"http://{self._host}:{self._port}{API_PREFIX}"

    async def request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a request against the device and return the parsed JSON body."""
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=json_body,
                headers={"Authorization": self._access_token},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status == 401:
                    raise KlyqaAuthError(f"Device {self._host} rejected the access token")
                text = await response.text()
                if response.status >= 400:
                    raise KlyqaConnectionError(
                        f"Device {self._host} answered HTTP {response.status} for {path}"
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KlyqaConnectionError(f"Request to {url} failed: {err}") from err
        try:
            body = json.loads(text)
        except json.JSONDecodeError as err:
            raise KlyqaConnectionError(f"Device {self._host} sent invalid JSON for {path}") from err
        if not isinstance(body, dict):
            raise KlyqaConnectionError(f"Device {self._host} sent unexpected JSON for {path}")
        if body.get("type") == "error":
            errors = body.get("error") or []
            error_msgs = [str(e) for e in errors] if isinstance(errors, list) else [str(errors)]
            raise KlyqaDeviceError(error_msgs)
        return body

    async def get_system_info(self) -> SystemInfo:
        """Return firmware and hardware information."""
        return SystemInfo.from_dict(await self.request("GET", "system/info"))

    async def reboot(self) -> None:
        """Reboot the device via the generic system command."""
        await self.request("PUT", "system/command", {"command": {"type": "reboot"}})
