"""Klyqa Foody pet feeder timer models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

from .device import _as_bool, _as_int
from .timecodes import decode_hhmm_lenient, decode_weekdays, encode_hhmm, encode_weekdays

# Maximum number of feeding schedules, per fw-foody.h
MAX_FEEDING_SCHEDULES = 20

# Maximum portion size (0-40), per device_timers.c
MAX_PORTIONS = 40

# Maximum total duration in seconds (0-10800), per device_timers.c
MAX_DURATION_SEC = 10800


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
            execution_time=decode_hhmm_lenient(_as_int(data.get("execution_time"))),
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
            start=decode_hhmm_lenient(_as_int(data.get("start_time"))),
            end=decode_hhmm_lenient(_as_int(data.get("end_time"))),
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
