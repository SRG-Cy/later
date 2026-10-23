"""Run with: uvicorn later.app:app"""

import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from later.models import Item
from later.pipeline import Deps, process_capture

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


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
            heard = await d.transcribe(await audio.read(), audio.content_type or "audio/webm")
            return await process_capture("voice", heard, None, d)
        if image is not None:
            return await process_capture("photo", text, await image.read(), d)
        if text and text.strip():
            return await process_capture("text", text.strip(), None, d)
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
    async def snooze(id: str, days: int = 3) -> Item:
        d = app.state.deps
        item = await find(id)
        if item.resolved is None:
            raise HTTPException(409, "Nothing scheduled to snooze")
        if await d.signal(id, "snooze", days):
            remind_at = item.resolved.remind_at + timedelta(days=days)
        else:  # the push already went out, so that workflow is finished: start a new one
            remind_at = d.now() + timedelta(days=days)
            await d.start(id, remind_at)
        resolved = item.resolved.model_copy(update={"remind_at": remind_at})
        await d.store.update(item.model_copy(update={"resolved": resolved, "status": "snoozed"}))
        return await find(id)

    return app


app = create_app()
