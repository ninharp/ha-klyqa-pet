"""Klyqa Foody pet feeder timer models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

from .device import _as_bool, _as_int

# Maximum number of feeding schedules, per fw-foody.h
MAX_FEEDING_SCHEDULES = 20

# Maximum portion size (0-40), per device_timers.c
MAX_PORTIONS = 40

# Maximum total duration in seconds (0-10800), per device_timers.c
MAX_DURATION_SEC = 10800


def decode_hhmm(value: int) -> time:
    """Decode an HHMM integer to a time object.

    Raises ValueError if the value is outside 0-2359 or has invalid minutes.
    """
    if value < 0 or value > 2359:
        raise ValueError(f"HHMM value must be 0-2359, got {value}")

    hours = value // 100
    minutes = value % 100

    if minutes > 59:
        raise ValueError(f"HHMM minutes must be 0-59, got {minutes}")

    return time(hours, minutes)


def _decode_hhmm_lenient(value: int) -> time:
    """Decode an HHMM integer, falling back to midnight on an impossible value.

    Every `from_dict` in this library is total: `_as_int`/`_as_bool` substitute a
    default rather than raise, so a surprising device response degrades one field
    instead of failing the whole poll. The times need the same treatment, because the
    firmware bounds `start_time`/`end_time` to 0-2359 but validates a schedule's
    `execution_time` only as "is a number" (device_timers.c), so any other client - or
    a corrupted NVS blob - can leave an out-of-range value there for the next GET to
    return. `decode_hhmm` stays strict for callers that want the validation.
    """
    try:
        return decode_hhmm(value)
    except ValueError:
        return time(0, 0)


def encode_hhmm(t: time) -> int:
    """Encode a time object to an HHMM integer."""
    return t.hour * 100 + t.minute


def decode_weekdays(mask: int) -> frozenset[int]:
    """Decode a weekday bitmask (bit 0=Sunday, bit 6=Saturday) to a frozenset of day indices."""
    return frozenset(i for i in range(7) if mask & (1 << i))


def encode_weekdays(days: frozenset[int]) -> int:
    """Encode a frozenset of day indices to a weekday bitmask (bit 0=Sunday, bit 6=Saturday)."""
    if any(day < 0 or day > 6 for day in days):
        raise ValueError(f"Weekday values must be 0-6, got {days}")

    mask = 0
    for day in days:
        mask |= 1 << day
    return mask


@dataclass(frozen=True, slots=True)
class FeedingSchedule:
    """A single feeding schedule for the Foody pet feeder."""

    schedule_id: int
    enabled: bool
    skip_once: bool
    execution_time: time
    weekdays: frozenset[int]
    portions: int
    total_duration_sec: int
    fresh_food_mode: bool
    auto_play_voice: bool
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeedingSchedule:
        """Parse a feeding schedule from the wire format."""
        return cls(
            schedule_id=_as_int(data.get("schedule_id")),
            enabled=_as_bool(data.get("enable")),
            skip_once=_as_bool(data.get("skip_once")),
            execution_time=_decode_hhmm_lenient(_as_int(data.get("execution_time"))),
            weekdays=decode_weekdays(_as_int(data.get("week_cycle"))),
            portions=_as_int(data.get("portions")),
            total_duration_sec=_as_int(data.get("total_duration_sec")),
            fresh_food_mode=_as_bool(data.get("fresh_food_mode")),
            auto_play_voice=_as_bool(data.get("auto_play_voice")),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the wire format."""
        return {
            "schedule_id": self.schedule_id,
            "enable": self.enabled,
            "skip_once": self.skip_once,
            "execution_time": encode_hhmm(self.execution_time),
            "week_cycle": encode_weekdays(self.weekdays),
            "portions": self.portions,
            "total_duration_sec": self.total_duration_sec,
            "fresh_food_mode": self.fresh_food_mode,
            "auto_play_voice": self.auto_play_voice,
        }


@dataclass(frozen=True, slots=True)
class SleepMode:
    """Sleep mode (do-not-disturb) configuration for the Foody pet feeder."""

    enabled: bool
    weekdays: frozenset[int]
    start: time
    end: time
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SleepMode:
        """Parse sleep mode from the wire format."""
        return cls(
            enabled=_as_bool(data.get("enable")),
            weekdays=decode_weekdays(_as_int(data.get("weekly_cycle"))),
            start=_decode_hhmm_lenient(_as_int(data.get("start_time"))),
            end=_decode_hhmm_lenient(_as_int(data.get("end_time"))),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the wire format."""
        return {
            "enable": self.enabled,
            "weekly_cycle": encode_weekdays(self.weekdays),
            "start_time": encode_hhmm(self.start),
            "end_time": encode_hhmm(self.end),
        }


@dataclass(frozen=True, slots=True)
class FoodyTimers:
    """Complete timer configuration for the Foody pet feeder."""

    schedules: tuple[FeedingSchedule, ...]
    sleep_mode: SleepMode
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FoodyTimers:
        """Parse the timer configuration from a device response."""
        schedules_data = data.get("schedules", [])
        schedules = tuple(FeedingSchedule.from_dict(schedule) for schedule in schedules_data)

        sleep_mode_data = data.get("sleep_mode", {})
        sleep_mode = SleepMode.from_dict(sleep_mode_data)

        return cls(
            schedules=schedules,
            sleep_mode=sleep_mode,
            raw=data,
        )
