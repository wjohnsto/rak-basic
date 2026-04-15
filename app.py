from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
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


def _tasks_html(tasks: list[Any], limit: int) -> str:
    rows = []
    for task in tasks:
        preview = escape(_task_preview(task)[:180] or "—")
        rows.append(
            "<tr>"
            f"<td><a href='/tasks/{escape(task.task_id)}'><code>{escape(task.task_id)}</code></a></td>"
            f"<td>{escape(task.status.value)}</td>"
            f"<td><code>{escape(task.session_id or '—')}</code></td>"
            f"<td>{escape(task.updated_at.isoformat(timespec='seconds'))}</td>"
            f"<td>{preview}</td>"
            f"<td><a href='/tasks/{escape(task.task_id)}/stream'>stream</a></td>"
            "</tr>"
        )
    body = (
        "".join(rows)
        or "<tr><td colspan='6'>No tasks yet. Submit one from <a href='/demo'>/demo</a>.</td></tr>"
    )
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Tasks</title><style>body{{margin:0;background:#f7f3eb;color:#211b17;font-family:Georgia,serif}}.shell{{max-width:1100px;margin:0 auto;padding:32px 20px}}.top{{display:flex;justify-content:space-between;gap:16px;align-items:end;flex-wrap:wrap;margin-bottom:20px}}.muted{{color:#6f6254}}.card{{background:#fffdf9;border:1px solid rgba(33,27,23,.12);border-radius:20px;padding:18px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 10px;border-bottom:1px solid rgba(33,27,23,.08);text-align:left;vertical-align:top}}th{{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#6f6254}}code{{font-family:Consolas,monospace}}a{{color:#b6461f;text-decoration:none}}a:hover{{text-decoration:underline}}</style></head><body><div class='shell'><div class='top'><div><h1 style='margin:0'>Tasks</h1><p class='muted'>Showing up to {limit} tasks from Redis Agent Kit.</p></div><div><a href='/demo'>/demo</a> · <a href='/protocol'>/protocol</a></div></div><div class='card'><table><thead><tr><th>Task</th><th>Status</th><th>Session</th><th>Updated</th><th>Preview</th><th>Events</th></tr></thead><tbody>{body}</tbody></table></div></div></body></html>"


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
