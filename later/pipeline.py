"""Capture -> facts -> (policy lookup) -> deadline -> stored item -> durable reminder."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from later.models import Facts, Item, Source
from later.resolve import DUBLIN, resolve
from later.store import ItemStore

log = logging.getLogger(__name__)
NO_DATE_NOTE ="No date printed, so counted from the day you captured it."


@dataclass
class Deps:
    store: ItemStore
    extract: Callable[[str | None, bytes | None, date], Awaitable[Facts | None]]
    lookup_days: Callable[[str], Awaitable[int | None]]
    start: Callable[[str, datetime], Awaitable[None]]
    signal: Callable[[str, str, Any], Awaitable[bool]]
    transcribe: Callable[[bytes, str], Awaitable[str]]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


def _needs_policy(f: Facts) -> bool:
    return (f.kind == "return_window" and bool(f.org) and f.explicit_due is None
            and f.window_days is None and f.window_months is None)


async def _quietly(call, *args):
    """An outside service failing must never lose the capture."""
    try:
        return await call(*args)
    except Exception:
        log.exception("%s failed", getattr(call, "__name__", "call"))
        return None


async def _complete_facts(f: Facts, deps: Deps) -> Facts:
    if _needs_policy(f) and (days := await _quietly(deps.lookup_days, f.org)):
        f = f.model_copy(update={"window_days": days,
                                 "evidence": f"{f.evidence} ({f.org} return policy online: {days} days)".strip()})
    has_window = f.window_days is not None or f.window_months is not None
    if f.anchor_date is None and f.explicit_due is None and has_window:
        f = f.model_copy(update={"evidence": f"{f.evidence} {NO_DATE_NOTE}".strip()})
    return f


async def process_capture(source: Source, text: str | None, image: bytes | None, deps: Deps) -> Item:
    now = deps.now()
    facts = await _quietly(deps.extract, text, image, now.astimezone(DUBLIN).date())
    item = Item(id=uuid.uuid4().hex, created_at=now.astimezone(UTC), source=source,
                raw_text=text or "", status="needs_info")
    if facts is not None:
        facts = await _complete_facts(facts, deps)
        resolved = resolve(facts, now)
        item = item.model_copy(update={"facts": facts, "resolved": resolved,
                                       "status": "scheduled" if resolved else "needs_info"})
    # Store first so the reminder activity always finds the item.
    await deps.store.insert(item)
    if item.resolved:
        try:
            await deps.start(item.id, item.resolved.remind_at)
        except Exception:
            log.exception("could not schedule reminder for %s", item.id)
            await deps.store.set_status(item.id, "failed")
            item = item.model_copy(update={"status": "failed"})
    return item
