"""Time and weekday encodings shared across Klyqa device families.

Wire encodings for times (as HHMM integers like 630 for 06:30) and weekdays
(as bitmasks where bit 0 is Sunday and bit 6 is Saturday) are shared between
the Foody feeder and Welly water fountain. These codecs provide strict and
lenient parsing variants for use by both device models.
"""

from __future__ import annotations

from datetime import time


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


def decode_hhmm_lenient(value: int) -> time:
    """Decode an HHMM integer, falling back to midnight on an impossible value.

    Every `from_dict` in this library is total: `_as_int`/`_as_bool` substitute a
    default rather than raise, so a surprising device response degrades one field
    instead of failing the whole poll. The times need the same treatment, because
    neither family's firmware range-checks every time it stores. The Foody bounds its
    sleep window but validates a schedule's execution time only as "is a number"; the
    Welly range-checks none of its times at all, taking the quiet-time window's start
    and end as plain numbers and casting a water-change entry's start straight to
    uint16 (device_timers.c in both firmwares). So any other client - or a corrupted
    NVS blob - can leave an out-of-range value there for the next GET to return.
    `decode_hhmm` stays strict for callers that want the validation.
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
