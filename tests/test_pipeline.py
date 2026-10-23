"""read_item: the background step that turns a stored capture into a deadline."""

from datetime import UTC, date

import pytest

from later.models import Item
from later.pipeline import read_item
from later.store import MemoryStore
from tests.helpers import CAPTURED, dublin, facts


class Model:
    def __init__(self, extracted=None, lookup=None, error=None):
        self.extracted, self.lookup, self.error = extracted, lookup, error
        self.args, self.lookups = None, []

    async def extract(self, text, image, today):
        self.args = (text, image, today)
        if self.error:
            raise self.error
        return self.extracted

    async def lookup_days(self, org):
        self.lookups.append(org)
        return self.lookup


async def stored(text="hello", image=None, status="reading") -> MemoryStore:
    store = MemoryStore()
    await store.insert(Item(id="i1", created_at=CAPTURED.astimezone(UTC), source="photo" if image else "text",
                            raw_text=text, status=status))
    if image:
        await store.put_blob("i1", image)
    return store


async def read(store, model):
    return await read_item("i1", store, model.extract, model.lookup_days)


async def test_schedules_and_returns_remind_at():
    store = await stored("Zara receipt")
    m = Model(facts(kind="return_window", anchor_date=date(2026, 10, 20), window_days=30))
    assert await read(store, m) == dublin(2026, 11, 16, 9, 0)
    item = await store.get("i1")
    assert item.status == "scheduled" and item.facts.window_days == 30
    assert m.args == ("Zara receipt", None, date(2026, 10, 23))


async def test_photo_bytes_are_read_from_store():
    store = await stored("", image=b"\xff\xd8jpeg")
    m = Model(None)
    await read(store, m)
    assert m.args[1] == b"\xff\xd8jpeg"


async def test_unreadable_is_needs_info():
    store = await stored()
    assert await read(store, Model(None)) is None
    assert (await store.get("i1")).status == "needs_info"


async def test_model_outage_raises_so_temporal_retries_and_item_stays_reading():
    store = await stored()
    with pytest.raises(RuntimeError):
        await read(store, Model(error=RuntimeError("500 from Google")))
    assert (await store.get("i1")).status == "reading"


async def test_policy_lookup_fills_window():
    store = await stored("Boots receipt")
    m = Model(facts(kind="return_window", org="Boots", anchor_date=date(2026, 10, 20)), lookup=28)
    await read(store, m)
    assert m.lookups == ["Boots"] and (await store.get("i1")).facts.window_days == 28


async def test_policy_outage_is_needs_info_not_a_retry_loop():
    store = await stored("Boots")
    m = Model(facts(kind="return_window", org="Boots", anchor_date=date(2026, 10, 20)))

    async def boom(org):
        raise RuntimeError("serpapi down")
    m.lookup_days = boom
    assert await read(store, m) is None
    assert (await store.get("i1")).status == "needs_info"


async def test_no_date_counts_from_capture_and_explains():
    store = await stored("receipt")
    await read(store, Model(facts(kind="return_window", window_days=14, anchor_date=None, evidence="")))
    item = await store.get("i1")
    assert item.resolved.due_at.date() == date(2026, 11, 6) and item.facts.evidence != ""


@pytest.mark.parametrize("status", ["cancelled", "done", "scheduled"])
async def test_item_no_longer_reading_is_left_alone(status):
    store = await stored(status=status)
    m = Model(facts(kind="bill", explicit_due=date(2026, 11, 2)))
    assert await read(store, m) is None
    assert m.args is None and (await store.get("i1")).status == status


async def test_missing_item_is_none():
    assert await read_item("nope", MemoryStore(), Model().extract, Model().lookup_days) is None
