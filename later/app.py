"""Run with: uvicorn later.app:app"""

import os
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from later.models import Item
from later.pipeline import Deps, accept_capture
from later.resolve import DUBLIN

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
MAX_PHOTO_BYTES = 4 * 1024 * 1024  # the page shrinks photos to well under this


async def build_deps() -> Deps:
    from temporalio.client import Client

    from later.llm import extract_facts
    from later.policy import lookup_return_days
    from later.store import MongoStore
    from later.tracing import init_tracing
    from later.voice import transcribe
    from later.workflow import signal, start_reminder

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


def create_app(deps: Deps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is None:
            app.state.deps = await build_deps()
        yield

    app = FastAPI(title="Later", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps

    async def find(id: str) -> Item:
        item = await app.state.deps.store.get(id)
        if item is None:
            raise HTTPException(404, "No such item")
        return item

    @app.get("/")
    async def index():
        return FileResponse(INDEX)

    @app.post("/capture")
    async def capture(text: str | None = Form(None), image: UploadFile | None = File(None),
                      audio: UploadFile | None = File(None)) -> Item:
        d = app.state.deps
        if audio is not None:
            try:
                heard = await d.transcribe(await audio.read(), audio.content_type or "audio/webm")
            except Exception:
                raise HTTPException(502, "Couldn't hear that voice note. Try again or type it instead.")
            return await accept_capture("voice", heard, None, d)
        if image is not None:
            data = await image.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "That photo is too big. Try again; the page shrinks it first.")
            return await accept_capture("photo", text, data, d)
        if text and text.strip():
            return await accept_capture("text", text.strip(), None, d)
        raise HTTPException(400, "Send a photo, a voice note or some text")

    @app.get("/items")
    async def items() -> list[Item]:
        return await app.state.deps.store.list_recent()

    async def finish(id: str, status: str, signal_name: str) -> Item:
        await find(id)
        await app.state.deps.store.set_status(id, status)
        await app.state.deps.signal(id, signal_name, None)  # False if the reminder already fired: fine
        return await find(id)

    @app.post("/items/{id}/done")
    async def done(id: str) -> Item:
        return await finish(id, "done", "done")

    @app.post("/items/{id}/cancel")
    async def cancel(id: str) -> Item:
        return await finish(id, "cancelled", "cancel")

    @app.post("/items/{id}/snooze")
    async def snooze(id: str, days: int = Query(3, ge=1, le=90)) -> Item:
        d = app.state.deps
        item = await find(id)
        if item.resolved is None:
            raise HTTPException(409, "Nothing scheduled to snooze")
        # Add calendar days in Irish local time so 09:00 stays 09:00 across a clock change.
        later_by = lambda t: (t.astimezone(DUBLIN) + timedelta(days=days)).astimezone(UTC)
        remind_at = later_by(item.resolved.remind_at)
        if not await d.signal(id, "snooze", remind_at.isoformat()):
            # The push already went out, so that workflow is finished: start a new one.
            remind_at = later_by(d.now())
            await d.start(id, remind_at)
        resolved = item.resolved.model_copy(update={"remind_at": remind_at})
        await d.store.update(item.model_copy(update={"resolved": resolved, "status": "snoozed"}))
        return await find(id)

    return app


app = create_app()
