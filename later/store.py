from typing import Protocol

from pymongo import AsyncMongoClient

from later.models import Item, Status


class ItemStore(Protocol):
    async def insert(self, item: Item) -> None: ...
    async def get(self, id: str) -> Item | None: ...
    async def list_recent(self, limit: int = 50) -> list[Item]: ...
    async def set_status(self, id: str, status: Status) -> None: ...
    async def update(self, item: Item) -> None: ...


class MemoryStore:
    def __init__(self):
        self._items: dict[str, Item] = {}

    async def insert(self, item: Item) -> None:
        self._items[item.id] = item

    async def get(self, id: str) -> Item | None:
        return self._items.get(id)

    async def list_recent(self, limit: int = 50) -> list[Item]:
        return sorted(self._items.values(), key=lambda i: i.created_at, reverse=True)[:limit]

    async def set_status(self, id: str, status: Status) -> None:
        if id in self._items:
            self._items[id] = self._items[id].model_copy(update={"status": status})

    async def update(self, item: Item) -> None:
        self._items[item.id] = item


class MongoStore:
    """Items are stored as JSON-mode dumps (BSON can't hold plain dates) plus a sortable timestamp."""

    def __init__(self, uri: str, db: str = "later"):
        self._col = AsyncMongoClient(uri, tz_aware=True)[db]["items"]

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

    async def list_recent(self, limit: int = 50) -> list[Item]:
        return [self._item(d) async for d in self._col.find().sort("_sort", -1).limit(limit)]

    async def set_status(self, id: str, status: Status) -> None:
        await self._col.update_one({"_id": id}, {"$set": {"status": status}})

    async def update(self, item: Item) -> None:
        await self._col.replace_one({"_id": item.id}, self._doc(item))
