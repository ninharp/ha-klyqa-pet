"""Klyqa Strype (RGBCW LED strip) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import STRYPE_MIN_TRANSITION_MS
from .device import KlyqaDevice, _as_int, _as_str


@dataclass(frozen=True, slots=True)
class StrypeState:
    """Parsed device/state of a Strype.

    A GET response is always complete: the firmware's `device_state_get_json` adds
    both `color` and `temperature` regardless of the active mode.

    A POST response is **partial**. The firmware assembles it mode-dependently: in
    `cct` mode it carries `temperature` but no `color`, in `rgb` mode `color` but no
    `temperature`, and in `cmd` mode neither. Absent keys are parsed as neutral
    values here (`rgb=(0, 0, 0)`, `temperature_kelvin=0`), so a state parsed from a
    POST response must not be treated as a full picture of the device. Only
    `length_ret` is unique to a POST response, which is why `length_metres` is None
    for states read via GET.
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

    async def _post_state(self, **fields: Any) -> StrypeState:
        """POST a state change and parse the (partial, see StrypeState) echo.

        The lighting firmware's message dispatcher rejects any message without a
        string `type` property and only routes `type == "request"` to the state
        handler, so every POST must carry it.
        """
        return StrypeState.from_dict(
            await self.request("POST", "device/state", {"type": "request", **fields})
        )

    async def set_state(
        self,
        *,
        power_on: bool | None = None,
        rgb: tuple[int, int, int] | None = None,
        temperature_kelvin: int | None = None,
        brightness_percent: int | None = None,
        transition_ms: int | None = None,
    ) -> StrypeState:
        """Apply the given changes and return the (partial) state the device echoes."""
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
            if power_on is not None:
                # `transitionTime` alone is ignored whenever the request actually flips
                # the power state: the firmware overwrites its fade time with the stored
                # fade-in/fade-out unless the matching `temp_fade` key is present. The
                # firmware clamps `transitionTime` to MIN_FADING_TIME but not
                # `temp_fade`, and reads a 0 there as "not given", so clamp it here to
                # keep both values in step.
                fade_ms = max(int(transition_ms), STRYPE_MIN_TRANSITION_MS)
                body["temp_fade"] = {"in": fade_ms} if power_on else {"out": fade_ms}
        return await self._post_state(**body)

    async def detect_length(self) -> StrypeState:
        """Re-measure the strip length; the response carries the new value."""
        return await self._post_state(length_detection=1)

    async def read_length(self) -> StrypeState:
        """Read the stored strip length via a side-effect-free POST."""
        return await self._post_state()
