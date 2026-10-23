"""Capture is instant; reading happens in the background (a Temporal activity), then the reminder waits.

accept_capture: store the raw capture as "reading" and start its workflow.
read_item:      facts -> (policy lookup) -> deadline. Model errors raise so Temporal retries them.
"""

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
NO_DATE_NOTE = "No date printed, so counted from the day you captured it."

Extract = Callable[[str | None, bytes | None, date], Awaitable[Facts | None]]
LookupDays = Callable[[str], Awaitable[int | None]]


@dataclass
class Deps:
    store: ItemStore
    extract: Extract
    lookup_days: LookupDays
    start: Callable[[str, datetime | None], Awaitable[None]]  # remind_at None = read first
    signal: Callable[[str, str, Any], Awaitable[bool]]
    transcribe: Callable[[bytes, str], Awaitable[str]]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


async def accept_capture(source: Source, text: str | None, image: bytes | None, deps: Deps) -> Item:
    item = Item(id=uuid.uuid4().hex, created_at=deps.now().astimezone(UTC), source=source,
                raw_text=text or "", status="reading")
    # Store first so the read activity always finds the item and its photo.
    await deps.store.insert(item)
    if image is not None:
        await deps.store.put_blob(item.id, image)
    try:
        await deps.start(item.id, None)
    except Exception:
        log.exception("could not start workflow for %s", item.id)
        await deps.store.set_status(item.id, "failed")
        item = item.model_copy(update={"status": "failed"})
    return item


def _needs_policy(f: Facts) -> bool:
    return (f.kind == "return_window" and bool(f.org) and f.explicit_due is None
            and f.window_days is None and f.window_months is None)


async def _complete_facts(f: Facts, lookup_days: LookupDays) -> Facts:
    days = None
    if _needs_policy(f):
        try:
            days = await lookup_days(f.org)
        except Exception:  # a missing return policy is not worth retrying the whole read for
            log.exception("policy lookup failed for %s", f.org)
    if days:
        f = f.model_copy(update={"window_days": days,
                                 "evidence": f"{f.evidence} ({f.org} return policy online: {days} days)".strip()})
    has_window = f.window_days is not None or f.window_months is not None
    if f.anchor_date is None and f.explicit_due is None and has_window:
        f = f.model_copy(update={"evidence": f"{f.evidence} {NO_DATE_NOTE}".strip()})
    return f


async def read_item(item_id: str, store: ItemStore, extract: Extract, lookup_days: LookupDays) -> datetime | None:
    """Returns when to remind, or None if there's nothing to schedule. Model errors propagate (retried)."""
    item = await store.get(item_id)
    if item is None or item.status != "reading":
        return None
    image = await store.get_blob(item_id) if item.source == "photo" else None
    facts = await extract(item.raw_text or None, image, item.created_at.astimezone(DUBLIN).date())
    resolved = None
    if facts is not None:
        facts = await _complete_facts(facts, lookup_days)
        resolved = resolve(facts, item.created_at)
    # Reading can take minutes: don't overwrite an item the person cancelled meanwhile.
    current = await store.get(item_id)
    if current is None or current.status != "reading":
        return None
    await store.update(item.model_copy(update={"facts": facts, "resolved": resolved,
                                               "status": "scheduled" if resolved else "needs_info"}))
    return resolved.remind_at if resolved else None
