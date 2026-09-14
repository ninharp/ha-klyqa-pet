from datetime import time
import json
from pathlib import Path

import pytest

from pyklyqa_pet.foody_timers import (
    FeedingSchedule,
    FoodyTimers,
    SleepMode,
    decode_hhmm,
    decode_weekdays,
    encode_hhmm,
    encode_weekdays,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "foody_timers.json").read_text())


def test_from_dict_parses_the_real_capture() -> None:
    timers = FoodyTimers.from_dict(FIXTURE)
    assert len(timers.schedules) == 1
    schedule = timers.schedules[0]
    assert schedule.schedule_id == 0
    assert schedule.enabled is True
    assert schedule.skip_once is False
    assert schedule.execution_time == time(6, 30)
    assert schedule.weekdays == frozenset(range(7))
    assert schedule.portions == 2
    assert timers.sleep_mode == SleepMode(
        enabled=False, weekdays=frozenset(range(7)), start=time(22, 0), end=time(6, 0)
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, time(0, 0)),
        (630, time(6, 30)),
        (957, time(9, 57)),
        (2200, time(22, 0)),
        (2359, time(23, 59)),
    ],
)
def test_hhmm_round_trip(raw: int, expected: time) -> None:
    assert decode_hhmm(raw) == expected
    assert encode_hhmm(expected) == raw


@pytest.mark.parametrize("raw", [-1, 2360, 1060, 99999])
def test_decode_hhmm_rejects_impossible_values(raw: int) -> None:
    with pytest.raises(ValueError):
        decode_hhmm(raw)


@pytest.mark.parametrize(
    ("mask", "days"),
    [
        (0, frozenset()),
        (127, frozenset(range(7))),
        (1, frozenset({0})),
        (64, frozenset({6})),
        (65, frozenset({0, 6})),
    ],
)
def test_weekday_round_trip(mask: int, days: frozenset[int]) -> None:
    assert decode_weekdays(mask) == days
    assert encode_weekdays(days) == mask


def test_schedule_to_dict_is_the_wire_shape() -> None:
    schedule = FeedingSchedule(
        schedule_id=3,
        enabled=True,
        skip_once=False,
        execution_time=time(18, 5),
        weekdays=frozenset({1, 2}),
        portions=4,
        total_duration_sec=0,
        fresh_food_mode=False,
        auto_play_voice=True,
    )
    assert schedule.to_dict() == {
        "schedule_id": 3,
        "enable": True,
        "skip_once": False,
        "execution_time": 1805,
        "week_cycle": 6,
        "portions": 4,
        "total_duration_sec": 0,
        "fresh_food_mode": False,
        "auto_play_voice": True,
    }


def test_sleep_mode_to_dict_is_the_wire_shape() -> None:
    assert SleepMode(
        enabled=True, weekdays=frozenset(range(7)), start=time(22, 0), end=time(8, 0)
    ).to_dict() == {"enable": True, "weekly_cycle": 127, "start_time": 2200, "end_time": 800}


def test_from_dict_tolerates_a_missing_schedules_array() -> None:
    timers = FoodyTimers.from_dict({"type": "timer"})
    assert timers.schedules == ()
    assert timers.sleep_mode.enabled is False
