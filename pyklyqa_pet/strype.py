"""Klyqa Strype (RGBCW LED strip) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import STRYPE_MIN_TRANSITION_MS
from .device import KlyqaDevice, _as_int, _as_str


@dataclass(frozen=True, slots=True)
class StrypeState:
    """State of a Strype, as reported by a `system/command` status response.

    The lighting firmware never reports the whole state at once. Its response callback
    adds `temperature` only while the strip is in `cct` mode and `color` only while it
    is in `rgb` mode; in `cmd` mode (an app-driven effect) it adds neither. The value
    for the inactive mode is not lost - the firmware keeps it - it is simply not sent,
    and there is no endpoint that would report it, so an absent key says nothing about
    the device and must never be read as "off"/"black"/"0".

    Every response is therefore merged onto the previously known state: see
    `from_dict`, which is the only place that decides what an absent key means.

    Note that `power_on` here is parsed from the response's `status` key, not from its
    `power_on` key. The latter is the device's power-on *behaviour* setting and stays
    put across an off/on cycle - confirmed on hardware, where `status` flipped
    "off"/"on" while `power_on` remained 0 throughout.
    """

    power_on: bool
    mode: str
    rgb: tuple[int, int, int]
    temperature_kelvin: int
    brightness_percent: int
    length_metres: int | None
    wifi_rssi: int | None
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], previous: StrypeState | None = None) -> StrypeState:
        """Parse a status response, carrying keys it omits over from `previous`.

        Every key that is present is authoritative. Every key that is absent is taken
        from `previous`, and only falls back to a neutral value when there is no
        previous state at all - the very first read of a device.

        This lives on the parser rather than in a separate merge helper because only
        the parser can still tell an absent key from a key that happens to carry a
        neutral value; once parsed, `temperature_kelvin=0` and "no `temperature` in the
        response" are indistinguishable, and a merge helper would have to guess.
        """
        color = data.get("color")
        if isinstance(color, dict):
            rgb = (
                _as_int(color.get("red")),
                _as_int(color.get("green")),
                _as_int(color.get("blue")),
            )
        else:
            rgb = previous.rgb if previous is not None else (0, 0, 0)

        brightness = data.get("brightness")
        if isinstance(brightness, dict):
            brightness_percent = _as_int(brightness.get("percentage"))
        else:
            brightness_percent = previous.brightness_percent if previous is not None else 0

        if "temperature" in data:
            temperature_kelvin = _as_int(data["temperature"])
        else:
            temperature_kelvin = previous.temperature_kelvin if previous is not None else 0

        if "status" in data:
            power_on = _as_str(data["status"]) == "on"
        else:
            power_on = previous.power_on if previous is not None else False

        if "mode" in data:
            mode = _as_str(data["mode"]) or "rgb"
        else:
            mode = previous.mode if previous is not None else "rgb"

        if "length_ret" in data:
            length_metres: int | None = _as_int(data["length_ret"])
        else:
            length_metres = previous.length_metres if previous is not None else None

        wifi = data.get("wifi_parameters")
        if isinstance(wifi, dict) and wifi.get("rssi") is not None:
            wifi_rssi: int | None = _as_int(wifi["rssi"])
        else:
            wifi_rssi = previous.wifi_rssi if previous is not None else None

        return cls(
            power_on=power_on,
            mode=mode,
            rgb=rgb,
            temperature_kelvin=temperature_kelvin,
            brightness_percent=brightness_percent,
            length_metres=length_metres,
            wifi_rssi=wifi_rssi,
            raw=data,
        )


class StrypeDevice(KlyqaDevice):
    """Client for the Klyqa Strype LED strip.

    Unlike the pet-line devices, the lighting firmware serves no `device/state` route
    at all: the `app_request_paths[]` table that would register it is commented out in
    `fw-klyqa-lighting_config.h` and `register_rest_endpoints()` is compiled out with
    `#if 0`, so an RGBCW build answers on `system/info`, `system/settings` and
    `system/command` and nothing else.

    All device traffic therefore goes through `PUT system/command`, whose SDK handler
    unwraps the request's `command` object and passes it to the lighting message
    dispatcher - which in turn rejects any message without a string `type` and routes
    only `type == "request"` to the state handler.
    """

    async def _command(self, previous: StrypeState | None, **fields: Any) -> StrypeState:
        """Send one `type: "request"` message and parse the status response."""
        return StrypeState.from_dict(
            await self.request("PUT", "system/command", {"command": {"type": "request", **fields}}),
            previous,
        )

    async def get_state(self, *, previous: StrypeState | None = None) -> StrypeState:
        """Read the current state with a request that carries no state-changing field.

        This firmware has no local state GET, so the only way to read the device is to
        send it a command that changes nothing. A request without `status`, `color`,
        `temperature`, `brightness` or `length_detection` sets no change flag, and the
        firmware applies power, colour, temperature, brightness and mode only inside
        its `if (changed > NOTHING_CHANGED)` block, so none of them are touched. The
        response still reports all of them.

        The one thing such a request does do is set the driver's fade time to the
        firmware default, because `lightbulb_set_fade_time()` sits outside that guard.
        That is invisible: the fade time only shapes the *next* transition, and every
        write this client sends passes `transitionTime` explicitly anyway.
        """
        return await self._command(previous)

    async def set_state(
        self,
        *,
        power_on: bool | None = None,
        rgb: tuple[int, int, int] | None = None,
        temperature_kelvin: int | None = None,
        brightness_percent: int | None = None,
        transition_ms: int | None = None,
        previous: StrypeState | None = None,
    ) -> StrypeState:
        """Apply the given changes and return the resulting state.

        The response is the same status message a read returns, so it is merged onto
        `previous` exactly the same way (see `StrypeState.from_dict`).
        """
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
                # fade-in/fade-out unless the matching `temp_fade` key is present.
                # Confirmed on hardware - with `temp_fade` the strip fades over the
                # requested time, with `transitionTime` alone it switches hard. The
                # firmware clamps `transitionTime` to MIN_FADING_TIME but not
                # `temp_fade`, and reads a 0 there as "not given", so clamp it here to
                # keep both values in step.
                fade_ms = max(int(transition_ms), STRYPE_MIN_TRANSITION_MS)
                body["temp_fade"] = {"in": fade_ms} if power_on else {"out": fade_ms}
        return await self._command(previous, **body)

    async def detect_length(self, *, previous: StrypeState | None = None) -> StrypeState:
        """Re-measure the strip length; the response carries the new value."""
        return await self._command(previous, length_detection=1)
