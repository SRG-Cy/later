"""The one push Later ever sends, via ntfy (open-source push). JSON publish keeps non-ASCII titles intact."""


import httpx

from later.models import Item
from later.resolve import DUBLIN
from later.security import item_token, public_base_url, topic_for

NTFY_URL = "https://ntfy.sh/"


async def notify(item: Item, http: httpx.AsyncClient | None = None) -> None:
    base = public_base_url()
    due = item.resolved.due_at.astimezone(DUBLIN)
    t = item_token(item.id)  # the ntfy app has no cookie, so the link itself proves who may press it
    action = lambda label, path: {"action": "http", "label": label,
                                  "url": f"{base}/items/{item.id}/{path}{'&' if '?' in path else '?'}t={t}",
                                  "method": "POST", "clear": True}
    payload = {
        "topic": topic_for(item.owner),
        "title": f"Later: {item.facts.title}",
        "message": f"{item.facts.action} (by {due:%a %d %b})",
        "actions": [action("Done", "done"), action("Snooze 3 days", "snooze?days=3")],
    }
    http = http or httpx.AsyncClient(timeout=15)
    resp = await http.post(NTFY_URL, json=payload)
    resp.raise_for_status()
