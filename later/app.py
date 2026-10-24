"""Run with: uvicorn later.app:app"""

import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from later.models import Item
from later.pipeline import Deps, accept_capture
from later.resolve import DUBLIN
from later.security import check_token, public_base_url, topic_for

STATIC = Path(__file__).resolve().parent.parent / "static"
INDEX = STATIC / "index.html"
MANIFEST = {
    "name": "Later", "short_name": "Later", "start_url": "/", "display": "standalone",
    "background_color": "#F5F7F8", "theme_color": "#2E6B57",
    "description": "Snap it, say it or type it. Later nudges you once, on the last sensible day.",
    "icons": [
        {"src": "/static/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/brand/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/brand/icon.svg", "sizes": "any", "type": "image/svg+xml"},
    ],
}
MAX_PHOTO_BYTES = 4 * 1024 * 1024  # the page shrinks photos to well under this
COOKIE = "later_visitor"


async def build_deps() -> Deps:
    from dotenv import load_dotenv
    from temporalio.client import Client

    from later.llm import extract_facts
    from later.policy import lookup_return_days
    from later.store import MongoStore
    from later.tracing import init_tracing
    from later.voice import transcribe
    from later.workflow import signal, start_reminder

    load_dotenv()  # local dev; real env vars win
    init_tracing()
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    return Deps(
        store=MongoStore(os.environ["MONGODB_URI"]),
        extract=extract_facts,
        lookup_days=lookup_return_days,
        start=lambda item_id, at: start_reminder(client, item_id, at),
        signal=lambda item_id, name, arg=None: signal(client, item_id, name, arg),
        transcribe=transcribe,
    )


def _visitor(request: Request, response: Response) -> str:
    """Anonymous visitor id in an httpOnly cookie: no sign-up, but people only see their own items."""
    vid = request.cookies.get(COOKIE)
    if not vid or len(vid) > 64:
        vid = secrets.token_urlsafe(16)
    response.set_cookie(COOKIE, vid, max_age=365 * 24 * 3600, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return vid


def create_app(deps: Deps | None = None, per_visitor_daily: int | None = None,
               total_daily: int | None = None) -> FastAPI:
    per_visitor_daily = per_visitor_daily or int(os.environ.get("DAILY_CAPTURES_PER_VISITOR", 10))
    total_daily = total_daily or int(os.environ.get("DAILY_CAPTURES_TOTAL", 200))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is None:
            app.state.deps = await build_deps()
        yield

    app = FastAPI(title="Later", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    async def find(id: str, owner: str, t: str | None = None) -> Item:
        item = await app.state.deps.store.get(id)
        # Same 404 for "missing" and "not yours", so ids can't be probed.
        if item is None or (item.owner != owner and not check_token(id, t)):
            raise HTTPException(404, "No such item")
        return item

    async def within_limits(owner: str) -> None:
        d = app.state.deps
        midnight = datetime.combine(d.now().astimezone(DUBLIN).date(), time(0), tzinfo=DUBLIN).astimezone(UTC)
        if await d.store.count_since(midnight, owner=owner) >= per_visitor_daily:
            raise HTTPException(429, "That's today's limit for this demo. Try again tomorrow.")
        if await d.store.count_since(midnight) >= total_daily:
            raise HTTPException(429, "The demo is busy today. Try again tomorrow.")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index():
        return FileResponse(INDEX)

    @app.get("/manifest.webmanifest")
    async def manifest():
        return JSONResponse(MANIFEST, media_type="application/manifest+json")

    @app.get("/healthz")
    async def healthz() -> dict:
        # The base the push buttons link to: not secret, and the first thing to check when they don't work.
        return {"ok": True, "public_base_url": public_base_url()}

    @app.get("/me")
    async def me(owner: str = Depends(_visitor)) -> dict:
        return {"topic": topic_for(owner)}

    @app.post("/capture")
    async def capture(text: str | None = Form(None), image: UploadFile | None = File(None),
                      audio: UploadFile | None = File(None), owner: str = Depends(_visitor)) -> Item:
        d = app.state.deps
        if audio is None and image is None and not (text and text.strip()):
            raise HTTPException(400, "Send a photo, a voice note or some text")
        await within_limits(owner)
        if audio is not None:
            try:
                heard = await d.transcribe(await audio.read(), audio.content_type or "audio/webm")
            except Exception:
                raise HTTPException(502, "Couldn't hear that voice note. Try again or type it instead.")
            return await accept_capture("voice", heard, None, d, owner)
        if image is not None:
            data = await image.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "That photo is too big. Try again; the page shrinks it first.")
            return await accept_capture("photo", text, data, d, owner)
        return await accept_capture("text", text.strip(), None, d, owner)

    @app.get("/items")
    async def items(owner: str = Depends(_visitor)) -> list[Item]:
        return await app.state.deps.store.list_recent(owner=owner)

    async def finish(id: str, owner: str, t: str | None, status: str, signal_name: str) -> Item:
        await find(id, owner, t)
        await app.state.deps.store.set_status(id, status)
        await app.state.deps.signal(id, signal_name, None)  # False if the reminder already fired: fine
        return await find(id, owner, t)

    @app.post("/items/{id}/done")
    async def done(id: str, t: str | None = None, owner: str = Depends(_visitor)) -> Item:
        return await finish(id, owner, t, "done", "done")

    @app.post("/items/{id}/cancel")
    async def cancel(id: str, t: str | None = None, owner: str = Depends(_visitor)) -> Item:
        return await finish(id, owner, t, "cancelled", "cancel")

    @app.post("/items/{id}/snooze")
    async def snooze(id: str, days: int = Query(3, ge=1, le=90), t: str | None = None,
                     owner: str = Depends(_visitor)) -> Item:
        d = app.state.deps
        item = await find(id, owner, t)
        if item.resolved is None:
            raise HTTPException(409, "Nothing scheduled to snooze")
        # Add calendar days in Irish local time so 09:00 stays 09:00 across a clock change.
        later_by = lambda at: (at.astimezone(DUBLIN) + timedelta(days=days)).astimezone(UTC)
        remind_at = later_by(item.resolved.remind_at)
        if not await d.signal(id, "snooze", remind_at.isoformat()):
            # The push already went out, so that workflow is finished: start a new one.
            remind_at = later_by(d.now())
            await d.start(id, remind_at)
        resolved = item.resolved.model_copy(update={"remind_at": remind_at})
        await d.store.update(item.model_copy(update={"resolved": resolved, "status": "snoozed"}))
        return await find(id, owner, t)

    return app


app = create_app()
