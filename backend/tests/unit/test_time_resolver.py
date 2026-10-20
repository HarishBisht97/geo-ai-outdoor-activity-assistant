from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.intent import TimeExpression
from app.utils.time_resolver import TimeResolutionError, resolve_window

# Tue 20 Oct 2026 10:00 IST
NOW = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
TZ = "Asia/Kolkata"


def resolve(duration=60, max_days=7, forecast_end=None, sun=None, **kw):
    return resolve_window(TimeExpression(**kw), now_utc=NOW, tz_name=TZ, duration_min=duration, max_days=max_days,
                          sun=sun, forecast_end_utc=forecast_end)


def local_hours(r):
    return [(s.strftime("%a %H:%M"), e.strftime("%a %H:%M")) for s, e in r.windows]


def test_tomorrow_morning():
    r = resolve(day_ref="tomorrow", part_of_day="morning")
    assert local_hours(r) == [("Wed 06:00", "Wed 11:00")]
    assert str(r.windows[0][0].tzinfo) == TZ


def test_this_weekend_morning_gives_two_windows():
    r = resolve(day_ref="this_weekend", part_of_day="morning")
    assert local_hours(r) == [("Sat 06:00", "Sat 11:00"), ("Sun 06:00", "Sun 11:00")]


def test_weekday_and_date():
    assert local_hours(resolve(day_ref="weekday", weekday="friday", part_of_day="evening")) == [
        ("Fri 16:00", "Fri 20:00")]
    assert resolve(day_ref="date", date="2026-10-24", part_of_day="afternoon").windows[0][0].day == 24


def test_days_ahead():
    r = resolve(day_ref="days_ahead", days_ahead=3, part_of_day="morning")
    assert r.windows[0][0].date().isoformat() == "2026-10-23"


def test_today_clips_to_now_plus_lead():
    r = resolve(day_ref="today", part_of_day="midday")  # 11-14, now 10:00
    assert r.windows[0][0] >= NOW + timedelta(minutes=30)
    r2 = resolve(day_ref="today", part_of_day="any")
    assert r2.windows[0][0] == NOW + timedelta(minutes=30)


def test_morning_already_over_is_past():
    with pytest.raises(TimeResolutionError):
        resolve(day_ref="today", part_of_day="morning")  # 06-11 with only 30 min left after the lead time


def test_no_time_given_evaluates_next_48h():
    r = resolve()
    assert r.end - r.start >= timedelta(hours=47)
    assert any("48 hours" in a for a in r.assumptions)


def test_implicit_day_uses_next_occurrence():
    r = resolve(part_of_day="morning")  # 10:00 now: today's morning is nearly over -> tomorrow
    assert r.windows[0][0].strftime("%a") == "Wed"
    assert any("No date was given" in a for a in r.assumptions)


def test_clock_time_one_hour_either_side():
    r = resolve(day_ref="tomorrow", clock_time="07:00")
    assert local_hours(r) == [("Wed 06:00", "Wed 08:00")] or r.windows[0][0].hour == 6
    assert r.requested_clock is not None and r.requested_clock.hour == 7


def test_past_time_raises():
    with pytest.raises(TimeResolutionError) as e:
        resolve(day_ref="today", part_of_day="early_morning")
    assert e.value.code == "past_time"


def test_beyond_horizon_raises():
    with pytest.raises(TimeResolutionError) as e:
        resolve(day_ref="days_ahead", days_ahead=12, part_of_day="morning")
    assert e.value.code == "beyond_horizon"
    with pytest.raises(TimeResolutionError) as e2:
        resolve(day_ref="weekday", weekday="sunday", part_of_day="morning",
                forecast_end=datetime(2026, 10, 23, 0, 0, tzinfo=UTC))
    assert e2.value.code == "beyond_horizon"
    assert "forecast" in e2.value.message


def test_sunset_window_uses_sun_times():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TZ)
    sun = {"2026-10-21": (datetime(2026, 10, 21, 6, 34, tzinfo=tz), datetime(2026, 10, 21, 18, 11, tzinfo=tz))}
    r = resolve(day_ref="tomorrow", part_of_day="sunset", sun=sun)
    s, e = r.windows[0]
    assert s < datetime(2026, 10, 21, 18, 11, tzinfo=tz) < e
