import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from later.models import Item
from later.store import MemoryStore, MongoStore


def make_item(minutes_ago: int = 0, **kw) -> Item:
    base = dict(id=uuid.uuid4().hex, created_at=datetime(2026, 10, 23, 12, tzinfo=UTC) - timedelta(minutes=minutes_ago),
                source="text", raw_text="hello", status="needs_info")
    base.update(kw)
    return Item(**base)


def stores():
    yield pytest.param(lambda: MemoryStore(), id="memory")
    uri = os.environ.get("MONGODB_URI")
    yield pytest.param(lambda: MongoStore(uri, db=f"later_test_{uuid.uuid4().hex[:6]}"), id="mongo",
                       marks=pytest.mark.skipif(not uri, reason="MONGODB_URI not set"))


@pytest.fixture(params=list(stores()))
def store(request):
    return request.param()


async def test_round_trip_keeps_utc(store):
    item = make_item()
    await store.insert(item)
    got = await store.get(item.id)
    assert got == item and got.created_at.utcoffset() == timedelta(0)


async def test_list_recent_newest_first(store):
    old, new = make_item(minutes_ago=10), make_item(minutes_ago=1)
    await store.insert(old)
    await store.insert(new)
    assert [i.id for i in await store.list_recent()][:2] == [new.id, old.id]


async def test_set_status(store):
    item = make_item()
    await store.insert(item)
    await store.set_status(item.id, "done")
    assert (await store.get(item.id)).status == "done"


async def test_set_status_unknown_is_noop(store):
    await store.set_status("nope", "done")
    assert await store.get("nope") is None


async def test_update_replaces(store):
    item = make_item()
    await store.insert(item)
    await store.update(item.model_copy(update={"raw_text": "changed"}))
    assert (await store.get(item.id)).raw_text == "changed"
