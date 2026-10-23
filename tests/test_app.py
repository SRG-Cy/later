from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from later.app import create_app
from later.pipeline import Deps
from later.store import MemoryStore
from tests.helpers import CAPTURED, DUBLIN, facts


class Recorder:
    def __init__(self, extracted=None, lookup=None, signal_ok=True, heard="voice text"):
        self.extracted, self.lookup, self.signal_ok, self.heard = extracted, lookup, signal_ok, heard
        self.started, self.signals, self.lookups, self.extract_args = [], [], [], None

    def deps(self, store):
        async def extract(text, image, today):
            self.extract_args = (text, image, today)
            return self.extracted

        async def lookup_days(org):
            self.lookups.append(org)
            return self.lookup

        async def start(item_id, remind_at):
            self.started.append((item_id, remind_at))

        async def signal(item_id, name, arg=None):
            self.signals.append((item_id, name, arg))
            return self.signal_ok

        async def transcribe(audio, mime):
            return self.heard

        return Deps(store=store, extract=extract, lookup_days=lookup_days, start=start, signal=signal,
                    transcribe=transcribe, now=lambda: CAPTURED)


def make(rec: Recorder):
    store = MemoryStore()
    return TestClient(create_app(rec.deps(store))), store


def test_text_capture_schedules():
    rec = Recorder(extracted=facts(kind="return_window", anchor_date=date(2026, 10, 20), window_days=30))
    client, _ = make(rec)
    r = client.post("/capture", data={"text": "Zara receipt"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scheduled" and len(rec.started) == 1
    assert rec.started[0][0] == body["id"]
    assert rec.extract_args[2] == date(2026, 10, 23)


def test_unreadable_capture_needs_info_and_no_workflow():
    rec = Recorder(extracted=None)
    client, _ = make(rec)
    body = client.post("/capture", data={"text": "???"}).json()
    assert body["status"] == "needs_info" and rec.started == []


def test_receipt_without_window_looks_up_policy():
    rec = Recorder(extracted=facts(kind="return_window", org="Boots", anchor_date=date(2026, 10, 20)), lookup=28)
    client, _ = make(rec)
    body = client.post("/capture", data={"text": "Boots receipt"}).json()
    assert rec.lookups == ["Boots"]
    assert body["facts"]["window_days"] == 28 and body["status"] == "scheduled"


def test_no_date_receipt_counts_from_capture_and_explains():
    rec = Recorder(extracted=facts(kind="return_window", window_days=14, anchor_date=None, evidence=""))
    client, _ = make(rec)
    body = client.post("/capture", data={"text": "receipt"}).json()
    assert body["resolved"]["due_at"].startswith("2026-11-06")
    assert body["facts"]["evidence"] != ""


def test_photo_is_passed_as_bytes():
    rec = Recorder(extracted=None)
    client, _ = make(rec)
    client.post("/capture", files={"image": ("r.jpg", b"\xff\xd8jpeg", "image/jpeg")})
    assert rec.extract_args[1] == b"\xff\xd8jpeg"


def test_voice_is_transcribed_then_extracted():
    rec = Recorder(extracted=None, heard="dentist in six months")
    client, _ = make(rec)
    body = client.post("/capture", files={"audio": ("v.webm", b"webm", "audio/webm")}).json()
    assert rec.extract_args[0] == "dentist in six months" and body["source"] == "voice"


def test_empty_capture_is_400():
    client, _ = make(Recorder())
    assert client.post("/capture", data={}).status_code == 400


def test_done_sets_status_and_signals():
    rec = Recorder(extracted=facts(kind="bill", explicit_due=date(2026, 11, 2)))
    client, store = make(rec)
    item_id = client.post("/capture", data={"text": "bill"}).json()["id"]
    assert client.post(f"/items/{item_id}/done").json()["status"] == "done"
    assert rec.signals[-1] == (item_id, "done", None)


def test_done_after_reminder_fired_is_still_ok():
    rec = Recorder(extracted=facts(kind="bill", explicit_due=date(2026, 11, 2)), signal_ok=False)
    client, _ = make(rec)
    item_id = client.post("/capture", data={"text": "bill"}).json()["id"]
    assert client.post(f"/items/{item_id}/done").status_code == 200


def test_snooze_after_reminder_fired_starts_new_reminder():
    rec = Recorder(extracted=facts(kind="bill", explicit_due=date(2026, 11, 2)), signal_ok=False)
    client, _ = make(rec)
    item_id = client.post("/capture", data={"text": "bill"}).json()["id"]
    body = client.post(f"/items/{item_id}/snooze?days=3").json()
    assert body["status"] == "snoozed"
    assert rec.started[-1] == (item_id, CAPTURED + timedelta(days=3))


def test_unknown_item_is_404():
    client, _ = make(Recorder())
    assert client.post("/items/nope/done").status_code == 404


def test_list_items_and_index_page():
    rec = Recorder(extracted=None)
    client, _ = make(rec)
    client.post("/capture", data={"text": "a"})
    assert len(client.get("/items").json()) == 1
    page = client.get("/")
    assert page.status_code == 200 and "Later" in page.text
