"""Deterministic resolution of relative time expressions into absolute windows.

The SLM only emits enums (day_ref, part_of_day, clock_time...). Dates are computed here from an explicit
reference time (server UTC now) in the *location's* IANA timezone. Multi-day requests produce one
window per day (e.g. "weekend mornings" -> Saturday 06-11 and Sunday 06-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.intent import TimeExpression

PART_OF_DAY_HOURS: dict[str, tuple[int, int]] = {
    "early_morning": (5, 8),
    "morning": (6, 11),
    "midday": (11, 14),
    "afternoon": (13, 17),
    "evening": (16, 20),
    "night": (19, 23),
    "after_work": (17, 21),
    "any": (5, 22),
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MIN_LEAD = timedelta(minutes=30)
DEFAULT_SPAN = timedelta(hours=48)

SunLookup = dict[str, tuple[datetime | None, datetime | None]]


class TimeResolutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # past_time | beyond_horizon | invalid_date
        self.message = message


@dataclass
class ResolvedTime:
    windows: list[tuple[datetime, datetime]]
    tz: str
    assumptions: list[str] = field(default_factory=list)
    requested_clock: datetime | None = None

    @property
    def start(self) -> datetime:
        return min(w[0] for w in self.windows)

    @property
    def end(self) -> datetime:
        return max(w[1] for w in self.windows)


def _explicit_days(expr: TimeExpression, today: date) -> tuple[list[date], list[str]]:
    notes: list[str] = []
    ref = expr.day_ref
    if ref == "today":
        return [today], notes
    if ref == "tomorrow":
        return [today + timedelta(days=1)], notes
    if ref == "day_after_tomorrow":
        return [today + timedelta(days=2)], notes
    if ref in ("this_weekend", "next_weekend"):
        wd = today.weekday()
        sat = today - timedelta(days=1) if wd == 6 else today + timedelta(days=(5 - wd) % 7)
        if ref == "next_weekend":
            sat += timedelta(days=7)
            notes.append(f"Interpreted 'next weekend' as {sat.isoformat()} to {(sat + timedelta(days=1)).isoformat()}.")
        return [d for d in (sat, sat + timedelta(days=1)) if d >= today], notes
    if ref == "weekday" and expr.weekday:
        delta = (WEEKDAYS.index(expr.weekday) - today.weekday()) % 7
        return [today + timedelta(days=delta)], notes
    if ref == "date" and expr.date:
        try:
            return [date.fromisoformat(expr.date)], notes
        except ValueError as exc:
            raise TimeResolutionError("invalid_date", f"'{expr.date}' is not a valid date.") from exc
    if ref == "next_n_days" and expr.n_days:
        return [today + timedelta(days=i) for i in range(expr.n_days)], notes
    if ref == "days_ahead" and expr.days_ahead is not None:
        return [today + timedelta(days=expr.days_ahead)], notes
    return [], notes


def _day_window(
    d: date, expr: TimeExpression, tz: ZoneInfo, duration: timedelta, sun: SunLookup, notes: list[str]
) -> tuple[datetime, datetime]:
    part = expr.part_of_day
    if expr.clock_time:
        hh, mm = map(int, expr.clock_time.split(":"))
        clock = datetime.combine(d, time(hh, mm), tz)
        return clock - timedelta(hours=1), clock + duration + timedelta(hours=1)
    if part in ("sunrise", "sunset"):
        sr, ss = sun.get(d.isoformat(), (None, None))
        anchor = sr if part == "sunrise" else ss
        if anchor is None:
            h0, h1 = (5, 8) if part == "sunrise" else (16, 20)
            notes.append(f"{part.title()} time unavailable for {d.isoformat()}; used {h0:02d}:00-{h1:02d}:00.")
            return datetime.combine(d, time(h0), tz), datetime.combine(d, time(h1), tz)
        a = anchor.astimezone(tz)
        if part == "sunrise":
            return a - timedelta(minutes=60), a + timedelta(minutes=90)
        return a - timedelta(minutes=120), a + timedelta(minutes=30)
    h0, h1 = PART_OF_DAY_HOURS.get(part or "any", PART_OF_DAY_HOURS["any"])
    return datetime.combine(d, time(h0), tz), datetime.combine(d, time(h1), tz)


def resolve_window(
    expr: TimeExpression,
    *,
    now_utc: datetime,
    tz_name: str,
    duration_min: int,
    max_days: int,
    sun: SunLookup | None = None,
    forecast_end_utc: datetime | None = None,
) -> ResolvedTime:
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    today = now_local.date()
    earliest = now_local + MIN_LEAD
    horizon = earliest + timedelta(days=max_days)
    duration = timedelta(minutes=duration_min)
    sun = sun or {}

    days, notes = _explicit_days(expr, today)
    implicit_day = not days
    requested_clock = None

    if implicit_day and not expr.clock_time and (expr.part_of_day in (None, "any")):
        windows = [(earliest, now_local + DEFAULT_SPAN)]
        notes.append("No date or time was given: evaluated the next 48 hours.")
    else:
        if implicit_day:
            days = [today, today + timedelta(days=1), today + timedelta(days=2)]
        windows = [_day_window(d, expr, tz, duration, sun, notes) for d in days]
        if implicit_day:
            upcoming = [w for w in windows if w[1] - duration > earliest]
            windows = upcoming[:1] or windows[:1]
            what = expr.clock_time or (expr.part_of_day or "").replace("_", " ")
            notes.append(f"No date was given: used the next {what} ({windows[0][0].date().isoformat()}).")
        if expr.clock_time:
            requested_clock = windows[0][0] + timedelta(hours=1)
            notes.append(f"Compared {expr.clock_time} with one hour either side.")
        if len(windows) > 1 and expr.part_of_day and expr.part_of_day != "any":
            notes.append(f"Evaluated the {expr.part_of_day.replace('_', ' ')} window on each requested day.")

    limit = horizon
    if forecast_end_utc is not None:
        limit = min(limit, forecast_end_utc.astimezone(tz))

    clipped: list[tuple[datetime, datetime]] = []
    for s, e in windows:
        s2, e2 = max(s, earliest), min(e, limit)
        if e2 - s2 >= timedelta(minutes=min(duration_min, 60)):
            clipped.append((s2, e2))
        if e > limit and e2 > s2:
            notes.append("Part of the requested window lies beyond the forecast horizon and was not evaluated.")

    if not clipped:
        if all(e <= earliest + timedelta(minutes=min(duration_min, 60)) for _, e in windows):
            raise TimeResolutionError("past_time", "The requested time has already passed in the location's timezone.")
        if forecast_end_utc is not None and all(s >= limit for s, _ in windows):
            raise TimeResolutionError(
                "beyond_horizon",
                f"The forecast currently covers until {limit.strftime('%a %d %b %H:%M')} local time; "
                "the requested time is beyond that.",
            )
        if all(s >= horizon for s, _ in windows):
            raise TimeResolutionError(
                "beyond_horizon", f"Requests are limited to the next {max_days} days of forecasts."
            )
        raise TimeResolutionError("past_time", "Too little of the requested window remains to evaluate.")

    return ResolvedTime(windows=clipped, tz=tz_name, assumptions=list(dict.fromkeys(notes)),
                        requested_clock=requested_clock)
