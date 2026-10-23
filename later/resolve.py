"""Turn extracted facts into a due time and a reminder time. All date math lives here."""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from later.models import Facts, Kind, Resolved

DUBLIN = ZoneInfo("Europe/Dublin")
REMIND_AT = time(9, 0)
END_OF_DAY = time(23, 59)

LEAD: dict[Kind, timedelta] = {
    "return_window": timedelta(days=3),
    "warranty": timedelta(days=30),
    "bill": timedelta(days=3),
    "appointment": timedelta(days=14),
    "deadline": timedelta(days=2),
    "event_tickets": timedelta(minutes=30),
    "other": timedelta(days=1),
}


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _due(facts: Facts, captured_at: datetime) -> datetime | None:
    due = facts.explicit_due
    if isinstance(due, datetime):
        return due if due.tzinfo else due.replace(tzinfo=DUBLIN)
    if due is None:
        if facts.window_days is None and facts.window_months is None:
            return None
        due = facts.anchor_date or captured_at.astimezone(DUBLIN).date()
        due = add_months(due, facts.window_months or 0) + timedelta(days=facts.window_days or 0)
    return datetime.combine(due, END_OF_DAY, tzinfo=DUBLIN)


def resolve(facts: Facts, captured_at: datetime) -> Resolved | None:
    due_at = _due(facts, captured_at)
    if due_at is None:
        return None
    lead = LEAD[facts.kind]
    if facts.kind == "event_tickets":
        remind_at = due_at - lead
    else:
        # Lead is in calendar days; keep 09:00 local even across a clock change.
        remind_day = (due_at.astimezone(DUBLIN) - lead).date()
        remind_at = datetime.combine(remind_day, REMIND_AT, tzinfo=DUBLIN)
    late = remind_at < captured_at
    if late:
        remind_at = captured_at
    return Resolved(due_at=due_at.astimezone(UTC), remind_at=remind_at.astimezone(UTC), late=late)
