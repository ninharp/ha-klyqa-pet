"""Klyqa Foody (pet feeder) client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .device import KlyqaDevice, _as_bool, _as_int

MIN_PORTIONS = 1
MAX_PORTIONS = 40


def _opt_int(value: Any) -> int | None:
    return None if value is None else _as_int(value)


@dataclass(frozen=True, slots=True)
class FoodyState:
    """Parsed GET device/state of a Foody (read-only shadow of the MCU status)."""

    power_state: bool
    adapter_state: bool
    battery_level: int
    food_bin_state: int
    bowl_state: int
    feeding_state: int
    error_state: int
    led_indicator: bool
    app_pet_lock: bool
    beep_switch: bool
    bowl_remaining: int
    last_manual_report: int
    last_manual_portions: int
    last_scheduled_report: int
    last_scheduled_portions: int
    next_feed_time: int
    last_realtime_weight: int
    last_portion_weight: int
    mcu_sw_version: int | None
    mcu_hw_version: int | None
    wifi_rssi: int | None
    timestamp: int
    error_log: list[dict[str, Any]]
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FoodyState:
        """Parse the state JSON object."""
        manual = data.get("last_manual_feeding") or {}
        scheduled = data.get("last_scheduled_feeding") or {}
        mcu = data.get("mcu_version")
        wifi = data.get("wifi_parameters") or {}
        error_log = data.get("error_log")
        return cls(
            power_state=_as_bool(data.get("power_state")),
            adapter_state=_as_bool(data.get("adapter_state")),
            battery_level=_as_int(data.get("battery_level"), -1),
            food_bin_state=_as_int(data.get("food_bin_state")),
            bowl_state=_as_int(data.get("bowl_state")),
            feeding_state=_as_int(data.get("feeding_state")),
            error_state=_as_int(data.get("error_state")),
            led_indicator=_as_bool(data.get("led_indicator")),
            app_pet_lock=_as_bool(data.get("app_pet_lock")),
            beep_switch=_as_bool(data.get("beep_switch")),
            bowl_remaining=_as_int(data.get("bowl_remaining")),
            last_manual_report=_as_int(manual.get("report_info")),
            last_manual_portions=_as_int(manual.get("portions_dispensed")),
            last_scheduled_report=_as_int(scheduled.get("report_info")),
            last_scheduled_portions=_as_int(scheduled.get("portions_dispensed")),
            next_feed_time=_as_int(scheduled.get("next_feed_time")),
            last_realtime_weight=_as_int(data.get("last_realtime_weight")),
            last_portion_weight=_as_int(data.get("last_portion_weight")),
            mcu_sw_version=_opt_int(mcu.get("sw_version")) if isinstance(mcu, dict) else None,
            mcu_hw_version=_opt_int(mcu.get("hw_version")) if isinstance(mcu, dict) else None,
            wifi_rssi=_opt_int(wifi.get("rssi")),
            timestamp=_as_int(data.get("ts")),
            error_log=list(error_log) if isinstance(error_log, list) else [],
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class FoodySettings:
    """Parsed GET/POST device/settings of a Foody."""

    app_led: bool
    app_pet_lock: bool
    custom_button_function: int
    beep_switch: bool
    feed_audio_enable: bool
    battery_work_mode: int
    charging_protection: int
    telemetry: bool
    feed_audio_volume: int
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FoodySettings:
        """Parse the settings JSON object."""
        return cls(
            app_led=_as_bool(data.get("app_led")),
            app_pet_lock=_as_bool(data.get("app_pet_lock")),
            custom_button_function=_as_int(data.get("custom_button_function")),
            beep_switch=_as_bool(data.get("beep_switch")),
            feed_audio_enable=_as_bool(data.get("feed_audio_enable")),
            battery_work_mode=_as_int(data.get("battery_work_mode")),
            charging_protection=_as_int(data.get("charging_protection"), 1),
            telemetry=_as_bool(data.get("telemetry", True)),
            feed_audio_volume=_as_int(data.get("feed_audio_volume"), 50),
            raw=data,
        )


class FoodyDevice(KlyqaDevice):
    """Client for the Klyqa Foody pet feeder."""

    async def get_state(self) -> FoodyState:
        """Return the current state."""
        return FoodyState.from_dict(await self.request("GET", "device/state"))

    async def get_settings(self) -> FoodySettings:
        """Return the persistent settings."""
        return FoodySettings.from_dict(await self.request("GET", "device/settings"))

    async def update_settings(self, **changes: bool | int) -> FoodySettings:
        """Change one or more settings and return the resulting settings."""
        return FoodySettings.from_dict(await self.request("POST", "device/settings", dict(changes)))

    async def dispense(self, portions: int) -> None:
        """Dispense the given number of portions (1..40)."""
        if not MIN_PORTIONS <= portions <= MAX_PORTIONS:
            raise ValueError(f"portions must be between {MIN_PORTIONS} and {MAX_PORTIONS}")
        await self.request(
            "POST",
            "device/control",
            {"action": "dispense", "control": 1, "portions": int(portions)},
        )

    async def play_voice_recording(self) -> None:
        """Play the stored custom voice recording (blocks until playback finished)."""
        await self.request("POST", "device/control", {"action": "play_voice_rec"})

    async def query_realtime_weight(self) -> None:
        """Ask the MCU for the current bowl weight; the result shows up in the state later."""
        await self.request("POST", "device/control", {"action": "query_realtime_weight"})
