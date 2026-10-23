"""The one push Later ever sends, via ntfy (open-source push). JSON publish keeps non-ASCII titles intact."""

import os

import httpx

from later.models import Item
from later.resolve import DUBLIN

NTFY_URL = "https://ntfy.sh/"


async def notify(item: Item, http: httpx.AsyncClient | None = None) -> None:
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    due = item.resolved.due_at.astimezone(DUBLIN)
    action = lambda label, path: {"action": "http", "label": label, "url": f"{base}/items/{item.id}/{path}",
                                  "method": "POST", "clear": True}
    payload = {
        "topic": os.environ["NTFY_TOPIC"],
        "title": f"Later: {item.facts.title}",
        "message": f"{item.facts.action} (by {due:%a %d %b})",
        "actions": [action("Done", "done"), action("Snooze 3 days", "snooze?days=3")],
    }
    http = http or httpx.AsyncClient(timeout=15)
    resp = await http.post(NTFY_URL, json=payload)
    resp.raise_for_status()
