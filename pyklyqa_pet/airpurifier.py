"""Klyqa Airpurifier client."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .device import KlyqaDevice, _as_bool, _as_int, _as_str

MIN_FAN_LEVEL = 1
MAX_FAN_LEVEL = 3


class AirPurifierRunMode(IntEnum):
    """Run modes of the air purifier."""

    STANDALONE = 0
    AUTO = 1
    NIGHT = 2
    PET = 3


@dataclass(frozen=True, slots=True)
class AirPurifierState:
    """Parsed GET device/state of an air purifier."""

    power: bool
    child_lock: bool
    key_tone: bool
    aqi_grade: int
    aqi_value: int
    fan_level: int
    run_mode: int
    pet_mode_time: int
    total_run_time: int
    air_volume: int
    filter_id: str
    filter_type: int
    filter_total_time: int
    filter_remaining_time: int
    led_custom: bool
    led_red: int
    led_green: int
    led_blue: int
    led_brightness: int
    ionizer_switch: bool
    ionizer_active: bool
    tilted: bool
    filter_removed: bool
    wifi_rssi: int | None
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AirPurifierState:
        """Parse the state JSON object."""
        color = data.get("color") or {}
        brightness = data.get("brightness") or {}
        wifi = data.get("wifi_parameters") or {}
        rssi = wifi.get("rssi")
        return cls(
            power=_as_bool(data.get("status")),
            child_lock=_as_bool(data.get("child_lock")),
            key_tone=_as_bool(data.get("key_tone")),
            aqi_grade=_as_int(data.get("aqi")),
            aqi_value=_as_int(data.get("aqi_num")),
            fan_level=_as_int(data.get("p_level")),
            run_mode=_as_int(data.get("run_mode")),
            pet_mode_time=_as_int(data.get("pet_tm")),
            total_run_time=_as_int(data.get("total_tm")),
            air_volume=_as_int(data.get("air_volume")),
            filter_id=_as_str(data.get("fid")),
            filter_type=_as_int(data.get("filter_type")),
            filter_total_time=_as_int(data.get("ftotal_tm")),
            filter_remaining_time=_as_int(data.get("fremain_tm")),
            led_custom=_as_bool(data.get("les")),
            led_red=_as_int(color.get("red")),
            led_green=_as_int(color.get("green")),
            led_blue=_as_int(color.get("blue")),
            led_brightness=_as_int(brightness.get("percentage")),
            ionizer_switch=_as_bool(data.get("anion_switch")),
            ionizer_active=_as_bool(data.get("anion_state")),
            tilted=_as_bool(data.get("tilt_status")),
            filter_removed=_as_bool(data.get("fremoval_status")),
            wifi_rssi=None if rssi is None else _as_int(rssi),
            raw=data,
        )


class AirPurifierDevice(KlyqaDevice):
    """Client for the Klyqa air purifier."""

    async def get_state(self) -> AirPurifierState:
        """Return the current state."""
        return AirPurifierState.from_dict(await self.request("GET", "device/state"))

    async def _post_state(self, **fields: Any) -> None:
        await self.request("POST", "device/state", {"type": "request", **fields})

    async def set_power(self, on: bool) -> None:
        """Switch the purifier on or off."""
        await self._post_state(status="on" if on else "off")

    async def set_fan_level(self, level: int) -> None:
        """Set the fan level (1..3)."""
        if not MIN_FAN_LEVEL <= level <= MAX_FAN_LEVEL:
            raise ValueError(f"fan level must be between {MIN_FAN_LEVEL} and {MAX_FAN_LEVEL}")
        await self._post_state(p_level=int(level))

    async def set_run_mode(self, mode: int) -> None:
        """Set the run mode (see AirPurifierRunMode)."""
        await self._post_state(run_mode=int(mode))

    async def set_led(self, on: bool, rgb: tuple[int, int, int] | None = None) -> None:
        """Enable custom LED colour (on=True with rgb) or return to automatic colour (on=False)."""
        if not on:
            await self._post_state(les="off")
            return
        fields: dict[str, Any] = {"les": "on"}
        if rgb is not None:
            fields["color"] = {"red": int(rgb[0]), "green": int(rgb[1]), "blue": int(rgb[2])}
        await self._post_state(**fields)

    async def set_ionizer(self, on: bool) -> None:
        """Enable or disable the ionizer."""
        await self._post_state(anion_switch=int(on))

    async def set_child_lock(self, on: bool) -> None:
        """Enable or disable the child lock."""
        await self._post_state(child_lock=int(on))

    async def set_key_tone(self, on: bool) -> None:
        """Enable or disable the key tone."""
        await self._post_state(key_tone=int(on))
