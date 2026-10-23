from collections.abc import Awaitable, Callable

from temporalio import activity

from later.models import Item
from later.store import ItemStore


class ReminderActivities:
    def __init__(self, store: ItemStore, notify: Callable[[Item], Awaitable[None]]):
        self.store, self.notify = store, notify

    @activity.defn(name="send_reminder")
    async def send_reminder(self, item_id: str) -> None:
        item = await self.store.get(item_id)
        if item is None or item.status not in ("scheduled", "snoozed"):
            return
        await self.notify(item)  # raises on failure, so Temporal retries
        await self.store.set_status(item_id, "reminded")
