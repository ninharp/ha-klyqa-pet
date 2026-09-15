from datetime import time

import pytest

from pyklyqa_pet.timecodes import (
    decode_hhmm,
    decode_weekdays,
    encode_hhmm,
    encode_weekdays,
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
