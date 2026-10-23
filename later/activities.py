from collections.abc import Awaitable, Callable

from temporalio import activity

from later.models import Item
from later.pipeline import Extract, LookupDays, read_item
from later.store import ItemStore


class ReminderActivities:
    def __init__(self, store: ItemStore, notify: Callable[[Item], Awaitable[None]],
                 extract: Extract | None = None, lookup_days: LookupDays | None = None):
        self.store, self.notify, self.extract, self.lookup_days = store, notify, extract, lookup_days

    @activity.defn(name="read_item")
    async def read_item(self, item_id: str) -> str | None:
        """Raises on model errors so Temporal retries; returns the reminder time as ISO, or None."""
        remind_at = await read_item(item_id, self.store, self.extract, self.lookup_days)
        return remind_at.isoformat() if remind_at else None

    @activity.defn(name="mark_failed")
    async def mark_failed(self, item_id: str) -> None:
        await self.store.set_status(item_id, "failed")

    @activity.defn(name="send_reminder")
    async def send_reminder(self, item_id: str) -> None:
        item = await self.store.get(item_id)
        if item is None or item.status not in ("scheduled", "snoozed"):
            return
        await self.notify(item)  # raises on failure, so Temporal retries
        await self.store.set_status(item_id, "reminded")
