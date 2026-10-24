import asyncio
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from later.app import create_app
from later.pipeline import Deps, read_item
from later.store import MemoryStore
from tests.helpers import CAPTURED, dublin, facts


class Recorder:
    def __init__(self, extracted=None, signal_ok=True, heard="voice text"):
        self.extracted, self.signal_ok, self.heard = extracted, signal_ok, heard
        self.started, self.signals = [], []

    def deps(self, store):
        async def extract(text, image, today):
            return self.extracted

        async def lookup_days(org):
            return None

        async def start(item_id, remind_at):
            self.started.append((item_id, remind_at))

        async def signal(item_id, name, arg=None):
            self.signals.append((item_id, name, arg))
            return self.signal_ok

        async def transcribe(audio, mime):
            return self.heard

        return Deps(store=store, extract=extract, lookup_days=lookup_days, start=start, signal=signal,
                    transcribe=transcribe, now=lambda: CAPTURED)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("LATER_SECRET", "s3cret")


def make(rec: Recorder, **limits):
    store = MemoryStore()
    return TestClient(create_app(rec.deps(store), **limits)), store


def capture_and_read(client, text="bill") -> str:
    """Capture, then run the background read step the workflow would run."""
    item_id = client.post("/capture", data={"text": text}).json()["id"]
    d = client.app.state.deps
    asyncio.run(read_item(item_id, d.store, d.extract, d.lookup_days))
    return item_id


def test_text_capture_returns_reading_and_starts_workflow():
    rec = Recorder()
    client, _ = make(rec)
    r = client.post("/capture", data={"text": "Zara receipt"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reading" and body["raw_text"] == "Zara receipt"
    assert rec.started == [(body["id"], None)]


def test_photo_is_stored_for_the_reader():
    rec = Recorder()
    client, store = make(rec)
    body = client.post("/capture", files={"image": ("r.jpg", b"\xff\xd8jpeg", "image/jpeg")}).json()
    assert body["source"] == "photo" and asyncio.run(store.get_blob(body["id"])) == b"\xff\xd8jpeg"


def test_oversized_photo_is_413():
    client, _ = make(Recorder())
    big = b"\xff\xd8" + b"0" * (5 * 1024 * 1024)
    assert client.post("/capture", files={"image": ("r.jpg", big, "image/jpeg")}).status_code == 413


def test_voice_is_transcribed_into_raw_text():
    rec = Recorder(heard="dentist in six months")
    client, _ = make(rec)
    body = client.post("/capture", files={"audio": ("v.webm", b"webm", "audio/webm")}).json()
    assert body["raw_text"] == "dentist in six months" and body["source"] == "voice"


def test_empty_capture_is_400():
    client, _ = make(Recorder())
    assert client.post("/capture", data={}).status_code == 400


def test_workflow_start_failure_marks_item_failed():
    rec = Recorder()
    client, _ = make(rec)

    async def boom(*a):
        raise RuntimeError("temporal down")
    client.app.state.deps.start = boom
    r = client.post("/capture", data={"text": "bill"})
    assert r.status_code == 200 and r.json()["status"] == "failed"


def test_voice_outage_is_502():
    client, _ = make(Recorder())

    async def boom(*a):
        raise RuntimeError("elevenlabs down")
    client.app.state.deps.transcribe = boom
    assert client.post("/capture", files={"audio": ("v.webm", b"x", "audio/webm")}).status_code == 502


def test_done_sets_status_and_signals():
    rec = Recorder(facts(kind="bill", explicit_due=date(2026, 11, 2)))
    client, _ = make(rec)
    item_id = capture_and_read(client)
    assert client.post(f"/items/{item_id}/done").json()["status"] == "done"
    assert rec.signals[-1] == (item_id, "done", None)


def test_cancel_while_reading_is_ok():
    rec = Recorder()
    client, _ = make(rec)
    item_id = client.post("/capture", data={"text": "x"}).json()["id"]
    assert client.post(f"/items/{item_id}/cancel").json()["status"] == "cancelled"


def test_done_after_reminder_fired_is_still_ok():
    rec = Recorder(facts(kind="bill", explicit_due=date(2026, 11, 2)), signal_ok=False)
    client, _ = make(rec)
    assert client.post(f"/items/{capture_and_read(client)}/done").status_code == 200


def test_snooze_after_reminder_fired_starts_new_reminder():
    rec = Recorder(facts(kind="bill", explicit_due=date(2026, 11, 2)), signal_ok=False)
    client, _ = make(rec)
    item_id = capture_and_read(client)
    body = client.post(f"/items/{item_id}/snooze?days=3").json()
    assert body["status"] == "snoozed"
    assert rec.started[-1] == (item_id, CAPTURED + timedelta(days=3))


def test_snooze_while_reading_is_409():
    client, _ = make(Recorder())
    item_id = client.post("/capture", data={"text": "x"}).json()["id"]
    assert client.post(f"/items/{item_id}/snooze?days=3").status_code == 409


def test_snooze_keeps_local_time_across_clock_change():
    # remind_at is "now" (late bill): 12:00 Irish Summer Time on Oct 23; +3 days is Oct 26, after clocks go back
    rec = Recorder(facts(kind="bill", explicit_due=date(2026, 10, 26)))
    client, _ = make(rec)
    item_id = capture_and_read(client)
    body = client.post(f"/items/{item_id}/snooze?days=3").json()
    assert datetime.fromisoformat(body["resolved"]["remind_at"]) == dublin(2026, 10, 26, 12, 0)
    assert rec.signals[-1] == (item_id, "snooze", dublin(2026, 10, 26, 12, 0).isoformat())


@pytest.mark.parametrize("days", [0, -1, 91, 1000000000])
def test_snooze_days_out_of_range_rejected(days):
    rec = Recorder(facts(kind="bill", explicit_due=date(2026, 11, 2)))
    client, _ = make(rec)
    item_id = capture_and_read(client)
    assert client.post(f"/items/{item_id}/snooze?days={days}").status_code == 422


def test_unknown_item_is_404():
    client, _ = make(Recorder())
    assert client.post("/items/nope/done").status_code == 404


def test_list_items_and_index_page():
    client, _ = make(Recorder())
    client.post("/capture", data={"text": "a"})
    assert len(client.get("/items").json()) == 1
    page = client.get("/")
    assert page.status_code == 200 and "Later" in page.text


# --- endpoint protection ---

def test_capture_sets_private_visitor_cookie():
    client, _ = make(Recorder())
    r = client.post("/capture", data={"text": "x"})
    cookie = r.headers["set-cookie"].lower()
    assert "later_visitor=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_visitors_only_see_their_own_items():
    a, store = make(Recorder())
    b = TestClient(a.app)
    a.post("/capture", data={"text": "mine"})
    b.post("/capture", data={"text": "theirs"})
    assert [i["raw_text"] for i in a.get("/items").json()] == ["mine"]
    assert [i["raw_text"] for i in b.get("/items").json()] == ["theirs"]


def test_other_visitor_cannot_act_on_my_item():
    a, _ = make(Recorder())
    item_id = a.post("/capture", data={"text": "mine"}).json()["id"]
    b = TestClient(a.app)
    assert b.post(f"/items/{item_id}/cancel").status_code == 404


def test_signed_link_from_the_push_works_without_cookie():
    from later.security import item_token
    a, _ = make(Recorder())
    item_id = a.post("/capture", data={"text": "mine"}).json()["id"]
    phone = TestClient(a.app)  # the ntfy app has no cookie
    assert phone.post(f"/items/{item_id}/cancel?t={item_token(item_id)}").status_code == 200
    assert phone.post(f"/items/{item_id}/done?t=wrong").status_code == 404


def test_me_returns_this_visitors_topic():
    from later.security import topic_for
    client, _ = make(Recorder())
    client.post("/capture", data={"text": "x"})
    me = client.get("/me").json()
    assert me["topic"] == topic_for(client.cookies["later_visitor"])
    assert client.get("/me").json() == me


def test_per_visitor_daily_limit():
    client, _ = make(Recorder(), per_visitor_daily=2)
    assert [client.post("/capture", data={"text": str(i)}).status_code for i in range(3)] == [200, 200, 429]


def test_total_daily_limit():
    a, _ = make(Recorder(), total_daily=2)
    b = TestClient(a.app)
    assert a.post("/capture", data={"text": "1"}).status_code == 200
    assert b.post("/capture", data={"text": "2"}).status_code == 200
    assert TestClient(a.app).post("/capture", data={"text": "3"}).status_code == 429
