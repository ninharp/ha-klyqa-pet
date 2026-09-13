"""Klyqa Strype (RGBCW LED strip) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .device import KlyqaDevice, _as_int, _as_str


@dataclass(frozen=True, slots=True)
class StrypeState:
    """Parsed device/state of a Strype.

    The same shape is returned by GET and by POST; a POST response additionally
    carries `length_ret`, so `length_metres` is None for states read via GET.
    """

    power_on: bool
    mode: str
    rgb: tuple[int, int, int]
    temperature_kelvin: int
    brightness_percent: int
    length_metres: int | None
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrypeState:
        """Parse a state JSON object; missing keys fall back to neutral values."""
        color = data.get("color") or {}
        brightness = data.get("brightness") or {}
        length = data.get("length_ret")
        return cls(
            power_on=_as_str(data.get("status")) == "on",
            mode=_as_str(data.get("mode")) or "rgb",
            rgb=(
                _as_int(color.get("red")),
                _as_int(color.get("green")),
                _as_int(color.get("blue")),
            ),
            temperature_kelvin=_as_int(data.get("temperature")),
            brightness_percent=_as_int(brightness.get("percentage")),
            length_metres=None if length is None else _as_int(length),
            raw=data,
        )


class StrypeDevice(KlyqaDevice):
    """Client for the Klyqa Strype LED strip.

    The lighting firmware only exposes device/state; there is no settings or
    control endpoint.
    """

    async def get_state(self) -> StrypeState:
        """Return the current state (without the strip length)."""
        return StrypeState.from_dict(await self.request("GET", "device/state"))

    async def set_state(
        self,
        *,
        power_on: bool | None = None,
        rgb: tuple[int, int, int] | None = None,
        temperature_kelvin: int | None = None,
        brightness_percent: int | None = None,
        transition_ms: int | None = None,
    ) -> StrypeState:
        """Apply the given changes and return the state the device reports back."""
        body: dict[str, Any] = {}
        if power_on is not None:
            body["status"] = "on" if power_on else "off"
        if rgb is not None:
            body["color"] = {"red": int(rgb[0]), "green": int(rgb[1]), "blue": int(rgb[2])}
        if temperature_kelvin is not None:
            body["temperature"] = int(temperature_kelvin)
        if brightness_percent is not None:
            body["brightness"] = {"percentage": int(brightness_percent)}
        if transition_ms is not None:
            body["transitionTime"] = int(transition_ms)
        return StrypeState.from_dict(await self.request("POST", "device/state", body))

    async def detect_length(self) -> StrypeState:
        """Re-measure the strip length; the response carries the new value."""
        return StrypeState.from_dict(
            await self.request("POST", "device/state", {"length_detection": 1})
        )

    async def read_length(self) -> StrypeState:
        """Read the stored strip length via an empty, side-effect-free POST."""
        return StrypeState.from_dict(await self.request("POST", "device/state", {}))
