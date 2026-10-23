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


async def test_read_item_activity_returns_iso_for_the_workflow():
    from datetime import date
    from tests.helpers import facts
    store = MemoryStore()
    await store.insert(item().model_copy(update={"status": "reading", "facts": None, "resolved": None}))

    async def extract(text, image, today):
        return facts(kind="bill", explicit_due=date(2026, 11, 2))

    async def lookup(org):
        return None

    acts = ReminderActivities(store, None, extract, lookup)
    iso = await acts.read_item("abc")
    assert iso == "2026-10-30T09:00:00+00:00" and (await store.get("abc")).status == "scheduled"


async def test_mark_failed():
    store = MemoryStore()
    await store.insert(item().model_copy(update={"status": "reading"}))
    await ReminderActivities(store, None).mark_failed("abc")
    assert (await store.get("abc")).status == "failed"
