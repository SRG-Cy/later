import json
from datetime import UTC, date, datetime

import httpx

from later.models import Facts, Item, Resolved
from later.notify import notify


def item() -> Item:
    return Item(
        id="abc", created_at=datetime(2026, 10, 23, 11, tzinfo=UTC), source="photo", raw_text="", status="scheduled",
        facts=Facts(kind="return_window", title="Zara jacket", action="Return the jacket to Zara",
                    anchor_date=date(2026, 10, 20), window_days=30, org="Zara", evidence="30 days", confidence=0.9),
        resolved=Resolved(due_at=datetime(2026, 11, 19, 23, 59, tzinfo=UTC),
                          remind_at=datetime(2026, 11, 16, 9, tzinfo=UTC), late=False),
    )


async def test_publishes_json_with_done_and_snooze_actions(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "later-test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://later.example")
    seen = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)))
    await notify(item(), http=http)
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://ntfy.sh/" and req.method == "POST"
    assert body["topic"] == "later-test"
    assert body["title"] == "Later: Zara jacket"
    assert body["message"] == "Return the jacket to Zara (by Thu 19 Nov)"
    assert body["actions"] == [
        {"action": "http", "label": "Done", "url": "https://later.example/items/abc/done", "method": "POST", "clear": True},
        {"action": "http", "label": "Snooze 3 days", "url": "https://later.example/items/abc/snooze?days=3", "method": "POST", "clear": True},
    ]


async def test_server_error_raises_so_temporal_retries(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    try:
        await notify(item(), http=http)
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError")
