"""Klyqa Welly water fountain timer models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from .device import _as_bool, _as_int
from .timecodes import decode_hhmm_lenient, decode_weekdays, encode_hhmm, encode_weekdays

# Maximum number of water-change schedules, per MAX_TIMER_ENTRIES in fw-klyqa-welly.h
MAX_WATER_CHANGE_ENTRIES = 6

# Descale reminder interval bounds in days, per device_timers.c ("must be 1-30")
MIN_DESCALING_INTERVAL_DAYS = 1
MAX_DESCALING_INTERVAL_DAYS = 30


@dataclass(frozen=True, slots=True)
class WaterChangeEntry:
    """A single water-change schedule for the Welly water fountain."""

    entry_id: int
    enabled: bool
    start: time
    weekdays: frozenset[int]
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaterChangeEntry:
        """Parse a water-change entry from the wire format."""
        return cls(
            entry_id=_as_int(data.get("id")),
            enabled=_as_bool(data.get("enabled")),
            start=decode_hhmm_lenient(_as_int(data.get("start"))),
            weekdays=decode_weekdays(_as_int(data.get("repeat"))),
            raw=data,
        )

    def to_dict(self, *, include_id: bool) -> dict[str, Any]:
        """Convert to the wire format.

        The firmware's `add` operation assigns the id itself and must not receive one,
        while `mod` requires the id of the entry being edited - passing the wrong shape
        would create a new entry instead of editing one.
        """
        result: dict[str, Any] = {}
        if include_id:
            result["id"] = self.entry_id
        result["enabled"] = self.enabled
        result["start"] = encode_hhmm(self.start)
        result["repeat"] = encode_weekdays(self.weekdays)
        return result


@dataclass(frozen=True, slots=True)
class QuietTime:
    """Quiet-time (do-not-disturb) window for the Welly water fountain."""

    enabled: bool
    start: time
    end: time
    water_enabled: bool
    weekdays: frozenset[int]
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuietTime:
        """Parse the quiet-time window from the wire format."""
        return cls(
            enabled=_as_bool(data.get("enabled")),
            start=decode_hhmm_lenient(_as_int(data.get("start"))),
            end=decode_hhmm_lenient(_as_int(data.get("end"))),
            water_enabled=_as_bool(data.get("water_enabled")),
            weekdays=decode_weekdays(_as_int(data.get("repeat"))),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the wire format."""
        return {
            "enabled": self.enabled,
            "start": encode_hhmm(self.start),
            "end": encode_hhmm(self.end),
            "water_enabled": self.water_enabled,
            "repeat": encode_weekdays(self.weekdays),
        }


@dataclass(frozen=True, slots=True)
class DescalingReminder:
    """Descale reminder configuration for the Welly water fountain."""

    enabled: bool
    interval_days: int
    last_descale: datetime | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DescalingReminder:
        """Parse the descale reminder from the wire format.

        `last_descale_time == 0` means the device has never been descaled, not the
        Unix epoch - rendering 1 January 1970 in a timestamp sensor would be worse
        than showing nothing, so it parses to None.
        """
        last_descale_time = _as_int(data.get("last_descale_time"))
        last_descale = (
            datetime.fromtimestamp(last_descale_time, tz=UTC) if last_descale_time else None
        )
        return cls(
            enabled=_as_bool(data.get("enabled")),
            interval_days=_as_int(data.get("interval")),
            last_descale=last_descale,
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the wire format."""
        return {
            "enabled": self.enabled,
            "interval": self.interval_days,
        }


@dataclass(frozen=True, slots=True)
class WellyTimers:
    """Complete timer configuration for the Welly water fountain."""

    quiet_time: QuietTime
    descaling: DescalingReminder
    water_changes: tuple[WaterChangeEntry, ...]
    raw: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WellyTimers:
        """Parse the timer configuration from a device response."""
        quiet_time = QuietTime.from_dict(data.get("ndt_timer", {}))
        descaling = DescalingReminder.from_dict(data.get("dm_timer", {}))
        water_changes = tuple(
            WaterChangeEntry.from_dict(entry) for entry in data.get("water_change", [])
        )

        return cls(
            quiet_time=quiet_time,
            descaling=descaling,
            water_changes=water_changes,
            raw=data,
        )
