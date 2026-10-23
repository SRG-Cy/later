from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from later.models import Facts

DUBLIN = ZoneInfo("Europe/Dublin")


def dublin(*args) -> datetime:
    return datetime(*args, tzinfo=DUBLIN)


CAPTURED = dublin(2026, 10, 23, 12, 0)


def facts(**kw) -> Facts:
    base = dict(
        kind="other", title="Thing", action="Do the thing", anchor_date=None,
        explicit_due=None, window_days=None, window_months=None, org=None,
        evidence="test", confidence=0.9,
    )
    base.update(kw)
    return Facts(**base)


__all__ = ["DUBLIN", "dublin", "CAPTURED", "facts", "timedelta"]
