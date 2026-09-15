from datetime import UTC, datetime, time
import json
from pathlib import Path

import pytest

from pyklyqa_pet.welly_timers import (
    DescalingReminder,
    QuietTime,
    WaterChangeEntry,
    WellyTimers,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "welly_timers.json").read_text())


def test_from_dict_parses_the_real_capture() -> None:
    timers = WellyTimers.from_dict(FIXTURE)
    assert timers.quiet_time == QuietTime(
        enabled=False,
        start=time(22, 0),
        end=time(7, 0),
        water_enabled=False,
        weekdays=frozenset(range(7)),
    )
    assert timers.descaling.enabled is True
    assert timers.descaling.interval_days == 15
    assert timers.descaling.last_descale is None
    assert timers.water_changes == (
        WaterChangeEntry(entry_id=0, enabled=True, start=time(6, 30), weekdays=frozenset(range(7))),
    )


def test_a_real_last_descale_time_becomes_a_datetime() -> None:
    """Epoch 0 means never; any other value is a real timestamp."""
    data = {**FIXTURE, "dm_timer": {**FIXTURE["dm_timer"], "last_descale_time": 1788615614}}
    assert WellyTimers.from_dict(data).descaling.last_descale == datetime.fromtimestamp(
        1788615614, tz=UTC
    )


def test_quiet_time_to_dict_is_the_wire_shape() -> None:
    assert QuietTime(
        enabled=True,
        start=time(22, 0),
        end=time(7, 0),
        water_enabled=True,
        weekdays=frozenset({0, 6}),
    ).to_dict() == {
        "enabled": True,
        "start": 2200,
        "end": 700,
        "water_enabled": True,
        "repeat": 65,
    }


def test_descaling_to_dict_is_the_wire_shape() -> None:
    assert DescalingReminder(enabled=True, interval_days=28, last_descale=None).to_dict() == {
        "enabled": True,
        "interval": 28,
    }


def test_water_change_to_dict_omits_the_id_when_creating() -> None:
    entry = WaterChangeEntry(
        entry_id=3, enabled=True, start=time(6, 30), weekdays=frozenset({1, 2})
    )
    assert entry.to_dict(include_id=False) == {"enabled": True, "start": 630, "repeat": 6}
    assert entry.to_dict(include_id=True) == {
        "id": 3,
        "enabled": True,
        "start": 630,
        "repeat": 6,
    }


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("raw", [9999, -1, 1060])
def test_from_dict_degrades_an_impossible_quiet_time_to_midnight(field: str, raw: int) -> None:
    """The Welly firmware range-checks none of its times, so parsing must stay total.

    `ndt_timer`'s start and end are only checked for being numbers (device_timers.c),
    so the Klyqa app, another client or a corrupted NVS blob can leave a value no clock
    has. Raising here would fail the whole poll and take every Welly entity with it.
    """
    document = json.loads(json.dumps(FIXTURE))
    document["ndt_timer"][field] = raw
    quiet_time = WellyTimers.from_dict(document).quiet_time
    assert getattr(quiet_time, field) == time(0, 0)
    # The rest of the window still parses, and the raw value is kept for diagnostics.
    assert quiet_time.weekdays == frozenset(range(7))
    assert quiet_time.raw[field] == raw


@pytest.mark.parametrize("raw", [9999, -1, 1060])
def test_from_dict_degrades_an_impossible_water_change_start_to_midnight(raw: int) -> None:
    """`hw_timer`'s start is cast straight to uint16 by the firmware (device_timers.c),
    with no range check at all, so a GET can return one no clock has."""
    document = json.loads(json.dumps(FIXTURE))
    document["water_change"][0]["start"] = raw
    entry = WellyTimers.from_dict(document).water_changes[0]
    assert entry.start == time(0, 0)
    assert entry.entry_id == 0
    assert entry.raw["start"] == raw


def test_from_dict_tolerates_missing_sections() -> None:
    timers = WellyTimers.from_dict({"type": "timer"})
    assert timers.water_changes == ()
    assert timers.quiet_time.enabled is False
    assert timers.descaling.last_descale is None
