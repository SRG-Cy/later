from datetime import date, timedelta

from later.resolve import resolve
from tests.helpers import CAPTURED, DUBLIN, dublin, facts


def test_return_window_from_receipt():
    r = resolve(facts(kind="return_window", anchor_date=date(2026, 10, 20), window_days=30), CAPTURED)
    assert r.due_at == dublin(2026, 11, 19, 23, 59)
    assert r.remind_at == dublin(2026, 11, 16, 9, 0)
    assert not r.late


def test_no_anchor_uses_capture_date():
    r = resolve(facts(kind="return_window", anchor_date=None, window_days=14), CAPTURED)
    assert r.due_at == dublin(2026, 11, 6, 23, 59)


def test_month_math_clamps_to_month_end():
    r = resolve(facts(kind="appointment", anchor_date=date(2026, 8, 31), window_months=6), CAPTURED)
    assert r.due_at.astimezone(DUBLIN).date() == date(2027, 2, 28)
    assert r.remind_at == dublin(2027, 2, 14, 9, 0)


def test_event_tickets_exact_time_minus_30_min():
    r = resolve(facts(kind="event_tickets", explicit_due=dublin(2026, 10, 30, 9, 0)), CAPTURED)
    assert r.remind_at == dublin(2026, 10, 30, 8, 30)


def test_past_reminder_fires_now_and_is_late():
    r = resolve(facts(kind="warranty", anchor_date=date(2024, 11, 15), window_months=24), CAPTURED)
    assert r.due_at.astimezone(DUBLIN).date() == date(2026, 11, 15)
    assert r.remind_at == CAPTURED and r.late


def test_clock_change_keeps_nine_am_local():
    r = resolve(facts(kind="bill", explicit_due=date(2026, 10, 28)), CAPTURED)
    assert r.remind_at.astimezone(DUBLIN).hour == 9
    assert r.remind_at.astimezone(DUBLIN).utcoffset() == timedelta(0)  # Ireland on GMT after Oct 25


def test_nothing_to_resolve_returns_none():
    assert resolve(facts(kind="other"), CAPTURED) is None


def test_results_are_utc():
    r = resolve(facts(kind="bill", explicit_due=date(2026, 10, 28)), CAPTURED)
    assert r.due_at.utcoffset() == timedelta(0) and r.remind_at.utcoffset() == timedelta(0)


def test_absurd_window_is_unresolvable_not_a_crash():
    assert resolve(facts(kind="other", window_days=3650, anchor_date=date(9999, 6, 1)), CAPTURED) is None


def test_date_only_event_nudges_at_nine_that_morning():
    # A gig or ticket sale with no time known: 23:29 that night would be too late.
    r = resolve(facts(kind="event_tickets", explicit_due=date(2026, 11, 13)), CAPTURED)
    assert r.remind_at == dublin(2026, 11, 13, 9, 0) and not r.late


def test_event_with_a_time_still_nudges_30_minutes_before():
    r = resolve(facts(kind="event_tickets", explicit_due=dublin(2026, 11, 13, 20, 30)), CAPTURED)
    assert r.remind_at == dublin(2026, 11, 13, 20, 0)
