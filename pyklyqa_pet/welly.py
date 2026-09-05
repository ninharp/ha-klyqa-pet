"""Klyqa Welly (water fountain) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .device import KlyqaDevice, _as_bool, _as_int


class WellyMode(IntEnum):
    """Operating modes of the fountain."""

    SENSING = 0
    FRESH_WATER_24H = 1
    MANUAL_WATER_CHANGE = 2
    SELF_WASH = 3
    DROP_WATER = 4


def _opt_int(value: Any) -> int | None:
    return None if value is None else _as_int(value)


@dataclass(frozen=True, slots=True)
class WellyState:
    """Parsed GET device/state of a Welly."""

    mode: int
    state: int
    power_supply: int
    power_status: int
    battery_level: int | None
    charging: bool
    heating_enabled: bool
    heating_temperature: int
    water_temperature: int
    pump_status: int
    water_tray_low: bool
    descaling: int
    do_not_disturb: bool
    tank_clean: int
    tank_sewage: int
    drinking_duration: int
    drinking_volume: int
    total_consumption: int
    daily_goal: int
    last_drinking_time: int
    filter_enabled: bool
    filter_status: int
    filter_life_remaining: int | None
    light_id: int
    light_time: int
    wifi_rssi: int | None
    error_log: list[dict[str, Any]]
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WellyState:
        """Parse the state JSON object; missing keys fall back to neutral values."""
        power = data.get("power") or {}
        heating = data.get("heating") or {}
        tank = data.get("tank_volume") or {}
        drinking = data.get("drinking") or {}
        filt = data.get("ultrafiltration") or {}
        wifi = data.get("wifi_parameters") or {}
        error_log = data.get("error_log")
        return cls(
            mode=_as_int(data.get("mode")),
            state=_as_int(data.get("state")),
            power_supply=_as_int(power.get("supply")),
            power_status=_as_int(power.get("status")),
            battery_level=_opt_int(power.get("battery_level")),
            charging=_as_bool(power.get("charging")),
            heating_enabled=_as_bool(heating.get("enabled")),
            heating_temperature=_as_int(heating.get("temperature")),
            water_temperature=_as_int(data.get("water_temperature")),
            pump_status=_as_int(data.get("pump_status")),
            water_tray_low=_as_bool(data.get("water_tray_low")),
            descaling=_as_int(data.get("descaling"), -1),
            do_not_disturb=_as_bool(data.get("do_not_disturb")),
            tank_clean=_as_int(tank.get("clean")),
            tank_sewage=_as_int(tank.get("sewage")),
            drinking_duration=_as_int(drinking.get("duration")),
            drinking_volume=_as_int(drinking.get("volume")),
            total_consumption=_as_int(drinking.get("total_consumption")),
            daily_goal=_as_int(drinking.get("daily_goal")),
            last_drinking_time=_as_int(drinking.get("last_time")),
            filter_enabled=_as_bool(filt.get("enabled")),
            filter_status=_as_int(filt.get("status")),
            filter_life_remaining=_opt_int(filt.get("life_remaining")),
            light_id=_as_int(data.get("light_id")),
            light_time=_as_int(data.get("light_time")),
            wifi_rssi=_opt_int(wifi.get("rssi")),
            error_log=list(error_log) if isinstance(error_log, list) else [],
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class WellySettings:
    """Parsed GET/POST device/settings of a Welly."""

    light_switch: bool
    ambient_light_switch: bool
    sensor_mode_light: bool
    lowest_water_output_range: int
    highest_water_output_range: int
    radar_sensitivity: int
    radar_sensing_interval: int
    alert_clean_tank_low: bool
    threshold_clean_tank_low: int
    alert_dirty_tank_full: bool
    threshold_dirty_tank_full: int
    super_power_saving_mode: bool
    circulation_pump_speed: int
    telemetry: bool
    telemetry_interval: int
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WellySettings:
        """Parse the settings JSON object."""
        telemetry = data.get("telemetry", data.get("telemetry_enabled", True))
        return cls(
            light_switch=_as_bool(data.get("light_switch")),
            ambient_light_switch=_as_bool(data.get("ambient_light_switch")),
            sensor_mode_light=_as_bool(data.get("sensor_mode_light")),
            lowest_water_output_range=_as_int(data.get("lowest_water_output_range")),
            highest_water_output_range=_as_int(data.get("highest_water_output_range"), 100),
            radar_sensitivity=_as_int(data.get("radar_sensitivity")),
            radar_sensing_interval=_as_int(data.get("radar_sensing_interval")),
            alert_clean_tank_low=_as_bool(data.get("alert_clean_tank_low")),
            threshold_clean_tank_low=_as_int(data.get("threshold_clean_tank_low")),
            alert_dirty_tank_full=_as_bool(data.get("alert_dirty_tank_full")),
            threshold_dirty_tank_full=_as_int(data.get("threshold_dirty_tank_full")),
            super_power_saving_mode=_as_bool(data.get("super_power_saving_mode")),
            circulation_pump_speed=_as_int(data.get("circulation_pump_speed")),
            telemetry=_as_bool(telemetry),
            telemetry_interval=_as_int(data.get("telemetry_interval")),
            raw=data,
        )


class WellyDevice(KlyqaDevice):
    """Client for the Klyqa Welly water fountain."""

    async def get_state(self) -> WellyState:
        """Return the current state."""
        return WellyState.from_dict(await self.request("GET", "device/state"))

    async def get_settings(self) -> WellySettings:
        """Return the persistent settings."""
        return WellySettings.from_dict(await self.request("GET", "device/settings"))

    async def set_mode(self, mode: int) -> None:
        """Set the operating mode (see WellyMode)."""
        await self.request("POST", "device/state", {"mode": int(mode)})

    async def set_heating(self, enabled: bool, temperature: int | None = None) -> None:
        """Enable/disable heating, optionally with a target temperature in °C."""
        heating: dict[str, Any] = {"enabled": enabled}
        if temperature is not None:
            heating["temperature"] = int(temperature)
        await self.request("POST", "device/state", {"heating": heating})

    async def set_daily_goal(self, millilitres: int) -> None:
        """Set the daily drinking goal in ml."""
        await self.request("POST", "device/state", {"drinking": {"daily_goal": int(millilitres)}})

    async def set_light(self, light_id: int) -> None:
        """Select the LED effect by id."""
        await self.request("POST", "device/state", {"light_id": int(light_id)})

    async def set_descaling(self, start: bool) -> None:
        """Start (True) or stop (False) descaling mode; the device uses 0=start, 1=stop."""
        await self.request("POST", "device/state", {"descaling": 0 if start else 1})

    async def update_settings(self, **changes: bool | int) -> WellySettings:
        """Change one or more settings and return the resulting settings."""
        return WellySettings.from_dict(await self.request("POST", "device/settings", dict(changes)))
