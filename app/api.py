"""FastAPI app — POST /run streams swarm events as Server-Sent Events.

Run with:  uvicorn app.api:app --reload

Each SSE message has:
  - event: <SwarmEvent.type>
  - data:  <JSON payload>

Clients (curl / EventSource / fetch+ReadableStream) can dispatch on the event
name, or just JSON-decode `data` and switch on its `type` field.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.swarm import run_swarm

app = FastAPI(title="Agent Swarm", version="0.1.0")


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=2000)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/run")
async def run(req: RunRequest) -> EventSourceResponse:
    async def event_stream() -> AsyncIterator[dict]:
        async for evt in run_swarm(req.task):
            yield {
                "event": evt.type,
                "data": evt.model_dump_json(),
            }

    return EventSourceResponse(event_stream(), ping=15)


@app.post("/run-collect")
async def run_collect(req: RunRequest) -> dict:
    """Non-streaming variant — collects all events and returns them at the end.

    Useful for quick smoke tests when you don't want to deal with SSE parsing.
    """
    events: list[dict] = []
    async for evt in run_swarm(req.task):
        events.append(json.loads(evt.model_dump_json()))
    return {"events": events}
