from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from redis_agent_kit import (
    AgentCard,
    AgentKit,
    AgentManifest,
    ChannelScope,
    EmitterMiddleware,
    Skill,
    StreamConfig,
)
from redis_agent_kit.api import create_app
from redis_agent_kit.keys import RedisKeys

from agent import run_langgraph_agent, run_task

load_dotenv(Path(__file__).with_name(".env"))

REDIS_URL = (
    os.getenv("RAK_REDIS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379"
)
PREFIX = "rak"
QUEUE_NAME = "minimal_release_demo"
STREAM_CONFIG = StreamConfig(enabled=True, channels={ChannelScope.TASK})
EM_DASH = "\u2014"
STATIC_DIR = Path(__file__).with_name("static")
DEMO_HTML = (STATIC_DIR / "index.html").read_text()
PROTOCOL_HTML = (STATIC_DIR / "protocol.html").read_text()


def _create_kit() -> AgentKit:
    return AgentKit(
        redis_url=REDIS_URL,
        prefix=PREFIX,
        agent_callable=run_task,
        middleware=[
            EmitterMiddleware(start_message="Task queued. Waiting for a worker...")
        ],
        queue_name=QUEUE_NAME,
        stream_config=STREAM_CONFIG,
    )


_kit = _create_kit()
tasks = [_kit.worker_task]

agent_card = AgentCard(
    name="RAK Demo",
    description="A Redis Agent Kit demo app wrapping a LangGraph agent.",
    url="http://localhost:8000",
    skills=[
        Skill(
            id="demo",
            name="LangGraph Demo",
            description="Run a LangGraph agent with Redis-backed tasking and SSE",
        )
    ],
)

agent_manifest = AgentManifest(
    name="rak-minimal-demo",
    description="A Redis Agent Kit demo app wrapping a LangGraph agent.",
)

app = create_app(
    redis_url=REDIS_URL,
    prefix=PREFIX,
    queue_name=QUEUE_NAME,
    kit=_kit,
    stream_config=STREAM_CONFIG,
    enable_a2a=True,
    enable_acp=True,
    agent_card=agent_card,
    agent_manifest=agent_manifest,
    title="RAK LangGraph Demo",
    description="Small companion app showing Redis Agent Kit around a LangGraph agent.",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _task_preview(task: Any) -> str:
    if task.input_request:
        return task.input_request.prompt
    if isinstance(task.result, dict) and task.result.get("response"):
        return str(task.result["response"])
    if task.error_message:
        return task.error_message
    return ""


_STATUS_CLASS = {
    "done": "task-status--done",
    "failed": "task-status--failed",
    "cancelled": "task-status--failed",
    "running": "task-status--running",
    "queued": "task-status--running",
    "awaiting_input": "task-status--awaiting",
}


def _tasks_html(tasks: list[Any], limit: int) -> str:
    cards = []
    for task in tasks:
        preview = escape(_task_preview(task)[:180] or EM_DASH)
        status_val = escape(task.status.value)
        status_cls = _STATUS_CLASS.get(task.status.value, "")
        task_id = escape(task.task_id)
        cards.append(
            "<div class='task-card'>"
            f"<div class='task-card__cell' data-label='Task'>"
            f"<a class='task-card__id' href='/tasks/{task_id}'><code>{task_id}</code></a>"
            "</div>"
            f"<div class='task-card__cell' data-label='Status'>"
            f"<span class='task-status {status_cls}'>{status_val}</span>"
            "</div>"
            f"<div class='task-card__cell' data-label='Updated'>"
            f"<span class='task-card__time'>{escape(task.updated_at.isoformat(timespec='seconds'))}</span>"
            "</div>"
            f"<div class='task-card__cell' data-label='Preview'>"
            f"<span class='task-card__preview'>{preview}</span>"
            "</div>"
            f"<div class='task-card__cell' data-label='Events'>"
            f"<a class='task-card__stream' href='/tasks/{task_id}/stream'>Stream</a>"
            "</div>"
            "</div>"
        )
    if cards:
        body = "".join(cards)
    else:
        body = (
            "<div class='task-card task-card--empty'>"
            "No tasks yet. Submit one from <a href='/demo'>/demo</a>."
            "</div>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Tasks \u2014 RAK Demo</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'/>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin/>"
        "<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap' rel='stylesheet'/>"
        "<link rel='stylesheet' href='/static/css/tokens.css'/>"
        "<link rel='stylesheet' href='/static/css/styles.css'/>"
        "</head><body>"
        "<header class='site-header'>"
        "<div class='site-header__inner'>"
        "<h1 class='site-header__label'>Agent Kit Demo</h1>"
        "<nav class='site-header__nav'>"
        "<a href='/demo'>Chat</a>"
        "<a href='/tasks' class='active'>Tasks</a>"
        "<a href='/protocol'>Protocol</a>"
        "</nav></div></header>"
        "<div class='page-wrap'>"
        "<section class='hero'>"
        f"<p>Showing up to {limit} tasks</p>"
        "</section>"
        "<div class='tasks-list'>"
        "<div class='tasks-list__header' role='row'>"
        "<span role='columnheader'>Task</span>"
        "<span role='columnheader'>Status</span>"
        "<span role='columnheader'>Updated</span>"
        "<span role='columnheader'>Preview</span>"
        "<span role='columnheader'>Events</span>"
        "</div>"
        f"{body}"
        "</div>"
        "</div></body></html>"
    )


@app.middleware("http")
async def html_task_list_middleware(request: Request, call_next):
    if request.method == "GET" and request.url.path == "/tasks":
        try:
            requested_limit = int(request.query_params.get("limit", "50"))
        except ValueError:
            requested_limit = 50
        limit = min(max(requested_limit, 1), 200)
        raw_ids = await _kit.task_manager._redis.smembers(RedisKeys.all_tasks(PREFIX))
        task_ids = [
            task_id.decode() if isinstance(task_id, bytes) else task_id
            for task_id in raw_ids
        ]
        task_items = []
        for task_id in task_ids:
            task = await _kit.task_manager.get_task(task_id)
            if task:
                task_items.append(task)
        task_items.sort(key=lambda task: task.updated_at, reverse=True)
        task_items = task_items[:limit]
        if _wants_html(request):
            return HTMLResponse(_tasks_html(task_items, limit))
        return JSONResponse(
            {
                "tasks": [task.model_dump(mode="json") for task in task_items],
                "total": len(task_items),
            }
        )
    return await call_next(request)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo_ui() -> HTMLResponse:
    return HTMLResponse(DEMO_HTML)


@app.get("/protocol", response_class=HTMLResponse, include_in_schema=False)
async def protocol_ui() -> HTMLResponse:
    return HTMLResponse(PROTOCOL_HTML)


@app.post("/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    return await _kit.create_and_submit_task(
        message=body.message, session_id=body.session_id
    )


@app.post("/chat-inline")
async def chat_inline(body: ChatRequest) -> dict[str, Any]:
    result = await run_langgraph_agent(body.message)
    return {"mode": "inline", **result}
