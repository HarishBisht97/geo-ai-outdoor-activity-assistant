"""Hourly slot generation inside resolved windows.

A slot is [start, start + duration). Starts are on the hour (forecast resolution is hourly). When a window
is shorter than the activity duration, starts inside the window are still produced so the slot
overlaps the requested period (e.g. a 4 h golf round starting in the "morning" window).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_SLOTS = 200


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def _ceil_hour(dt: datetime) -> datetime:
    floor = dt.replace(minute=0, second=0, microsecond=0)
    return floor if floor == dt else floor + timedelta(hours=1)


def generate_slots(
    windows: list[tuple[datetime, datetime]],
    duration_min: int,
    coverage_end: datetime | None,
    step_h: int = 1,
) -> list[Slot]:
    duration = timedelta(minutes=duration_min)
    out: list[Slot] = []
    seen: set[datetime] = set()
    for w_start, w_end in windows:
        t = _ceil_hour(w_start)
        fitting = []
        loose = []
        while t < w_end:
            end = t + duration
            if coverage_end is None or end <= coverage_end + timedelta(hours=1):
                (fitting if end <= w_end else loose).append(Slot(t, end))
            t += timedelta(hours=step_h)
        chosen = fitting or loose
        for s in chosen:
            if s.start not in seen:
                seen.add(s.start)
                out.append(s)
    out.sort(key=lambda s: s.start)
    return out[:MAX_SLOTS]
