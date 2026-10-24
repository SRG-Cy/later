from datetime import datetime
from typing import Protocol

from pymongo import AsyncMongoClient

from later.models import Item, Status


class ItemStore(Protocol):
    async def insert(self, item: Item) -> None: ...
    async def get(self, id: str) -> Item | None: ...
    async def list_recent(self, limit: int = 50, owner: str | None = None) -> list[Item]: ...
    async def count_since(self, since: datetime, owner: str | None = None) -> int: ...
    async def set_status(self, id: str, status: Status) -> None: ...
    async def update(self, item: Item) -> None: ...
    async def put_blob(self, id: str, data: bytes) -> None: ...
    async def get_blob(self, id: str) -> bytes | None: ...


class MemoryStore:
    def __init__(self):
        self._items: dict[str, Item] = {}
        self._blobs: dict[str, bytes] = {}

    async def insert(self, item: Item) -> None:
        self._items[item.id] = item

    async def get(self, id: str) -> Item | None:
        return self._items.get(id)

    async def list_recent(self, limit: int = 50, owner: str | None = None) -> list[Item]:
        items = [i for i in self._items.values() if owner is None or i.owner == owner]
        return sorted(items, key=lambda i: i.created_at, reverse=True)[:limit]

    async def count_since(self, since: datetime, owner: str | None = None) -> int:
        return sum(1 for i in self._items.values() if i.created_at >= since and (owner is None or i.owner == owner))

    async def set_status(self, id: str, status: Status) -> None:
        if id in self._items:
            self._items[id] = self._items[id].model_copy(update={"status": status})

    async def update(self, item: Item) -> None:
        self._items[item.id] = item

    async def put_blob(self, id: str, data: bytes) -> None:
        self._blobs[id] = data

    async def get_blob(self, id: str) -> bytes | None:
        return self._blobs.get(id)


class MongoStore:
    """Items are stored as JSON-mode dumps (BSON can't hold plain dates) plus a sortable timestamp."""

    def __init__(self, uri: str, db: str = "later"):
        database = AsyncMongoClient(uri, tz_aware=True)[db]
        self._col, self._blobs = database["items"], database["blobs"]

    @staticmethod
    def _doc(item: Item) -> dict:
        return {**item.model_dump(mode="json"), "_id": item.id, "_sort": item.created_at}

    @staticmethod
    def _item(doc: dict) -> Item:
        doc.pop("_id"), doc.pop("_sort")
        return Item.model_validate(doc)

    async def insert(self, item: Item) -> None:
        await self._col.insert_one(self._doc(item))

    async def get(self, id: str) -> Item | None:
        doc = await self._col.find_one({"_id": id})
        return self._item(doc) if doc else None

    async def list_recent(self, limit: int = 50, owner: str | None = None) -> list[Item]:
        query = {} if owner is None else {"owner": owner}
        return [self._item(d) async for d in self._col.find(query).sort("_sort", -1).limit(limit)]

    async def count_since(self, since: datetime, owner: str | None = None) -> int:
        query = {"_sort": {"$gte": since}} | ({} if owner is None else {"owner": owner})
        return await self._col.count_documents(query)

    async def set_status(self, id: str, status: Status) -> None:
        await self._col.update_one({"_id": id}, {"$set": {"status": status}})

    async def update(self, item: Item) -> None:
        await self._col.replace_one({"_id": item.id}, self._doc(item))

    async def put_blob(self, id: str, data: bytes) -> None:
        await self._blobs.replace_one({"_id": id}, {"_id": id, "data": data}, upsert=True)

    async def get_blob(self, id: str) -> bytes | None:
        doc = await self._blobs.find_one({"_id": id})
        return bytes(doc["data"]) if doc else None
