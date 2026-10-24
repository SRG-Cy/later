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
    yield pytest.param("memory", id="memory")
    yield pytest.param("mongo", id="mongo",
                       marks=pytest.mark.skipif(not os.environ.get("MONGODB_URI"), reason="MONGODB_URI not set"))


@pytest.fixture(params=list(stores()))
async def store(request):
    if request.param == "memory":
        yield MemoryStore()
        return
    from pymongo import AsyncMongoClient
    uri, db = os.environ["MONGODB_URI"], f"later_test_{uuid.uuid4().hex[:6]}"
    yield MongoStore(uri, db=db)
    client = AsyncMongoClient(uri)
    await client.drop_database(db)  # leave the free cluster clean
    await client.close()


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


async def test_blob_round_trip(store):
    await store.put_blob("b1", b"\xff\xd8jpeg")
    assert await store.get_blob("b1") == b"\xff\xd8jpeg"
    assert await store.get_blob("missing") is None


async def test_list_recent_filters_by_owner(store):
    mine, theirs = make_item(owner="me"), make_item(owner="them")
    await store.insert(mine)
    await store.insert(theirs)
    assert [i.id for i in await store.list_recent(owner="me")] == [mine.id]


async def test_count_since(store):
    await store.insert(make_item(minutes_ago=5, owner="me"))
    await store.insert(make_item(minutes_ago=5, owner="them"))
    await store.insert(make_item(minutes_ago=60 * 30, owner="me"))  # yesterday
    since = datetime(2026, 10, 23, tzinfo=UTC)
    assert await store.count_since(since, owner="me") == 1
    assert await store.count_since(since) == 2
