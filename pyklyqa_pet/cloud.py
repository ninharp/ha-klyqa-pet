"""Client for the Klyqa / QConnex cloud API (used only to obtain device tokens)."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from .const import CLOUD_BASE_URLS, REQUEST_TIMEOUT, Environment
from .exceptions import KlyqaAuthError, KlyqaConnectionError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CloudDevice:
    """A device registered in the user's cloud account."""

    local_device_id: str
    access_token: str
    name: str
    product_id: str
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CloudDevice | None:
        """Build from a cloud `devices[]` entry; None if the entry is unusable."""
        local_device_id = str(data.get("localDeviceId") or "").upper()
        access_token = str(data.get("accessToken") or "")
        if not local_device_id or not access_token:
            return None
        return cls(
            local_device_id=local_device_id,
            access_token=access_token,
            name=str(data.get("name") or ""),
            product_id=str(data.get("productId") or ""),
            raw=data,
        )


class KlyqaCloudClient:
    """Minimal cloud client: login and list devices with their local access tokens."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        environment: Environment,
        *,
        base_url: str | None = None,
    ) -> None:
        """Create the client using an externally managed aiohttp session.

        `base_url` overrides the environment's cloud URL (used by tests).
        """
        self._session = session
        self._base_url = (base_url or CLOUD_BASE_URLS[environment]).rstrip("/")
        self._account_token: str | None = None

    @property
    def account_token(self) -> str | None:
        """Return the account token obtained by login, if any."""
        return self._account_token

    async def login(self, email: str, password: str) -> str:
        """Authenticate and return the account token."""
        try:
            async with self._session.post(
                f"{self._base_url}/auth/login",
                json={"email": email, "password": password},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (400, 401, 403):
                    raise KlyqaAuthError("Cloud login rejected")
                if response.status not in (200, 201):
                    raise KlyqaConnectionError(f"Cloud login failed with HTTP {response.status}")
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KlyqaConnectionError(f"Cloud login request failed: {err}") from err
        token = body.get("accountToken") if isinstance(body, dict) else None
        if not token:
            raise KlyqaAuthError("Cloud login response did not contain an account token")
        self._account_token = str(token)
        return self._account_token

    async def list_devices(self) -> list[CloudDevice]:
        """Return all devices of the account with their local access tokens."""
        if self._account_token is None:
            raise KlyqaAuthError("Not logged in")
        try:
            async with self._session.get(
                f"{self._base_url}/settings",
                headers={"Authorization": f"Bearer {self._account_token}"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise KlyqaAuthError("Cloud account token rejected")
                if response.status != 200:
                    raise KlyqaConnectionError(f"Cloud settings failed with HTTP {response.status}")
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KlyqaConnectionError(f"Cloud settings request failed: {err}") from err
        raw_devices = body.get("devices", []) if isinstance(body, dict) else []
        devices: list[CloudDevice] = []
        for raw in raw_devices:
            device = CloudDevice.from_dict(raw) if isinstance(raw, dict) else None
            if device is None:
                _LOGGER.debug("Skipping cloud device entry without id or token")
                continue
            devices.append(device)
        return devices
