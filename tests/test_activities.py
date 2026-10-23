from later.activities import ReminderActivities
from later.store import MemoryStore
from tests.test_notify import item


async def test_send_reminder_notifies_and_marks_reminded():
    store, sent = MemoryStore(), []
    await store.insert(item())

    async def fake_notify(i):
        sent.append(i.id)

    await ReminderActivities(store, fake_notify).send_reminder("abc")
    assert sent == ["abc"] and (await store.get("abc")).status == "reminded"


async def test_missing_or_finished_item_is_skipped():
    store, sent = MemoryStore(), []
    await store.insert(item().model_copy(update={"status": "done"}))

    async def fake_notify(i):
        sent.append(i.id)

    acts = ReminderActivities(store, fake_notify)
    await acts.send_reminder("abc")
    await acts.send_reminder("missing")
    assert sent == []
