# RAK demo

This repo is a minimal Redis Agent Kit example.

It shows:

- background task execution with workers
- live progress and token streaming over SSE
- a real LangGraph agent behind the task interface
- REST, A2A, and ACP exposure from one app

The main point is that this does not require much code. The API entry point stays small in
[app.py](app.py), and the actual agent implementation lives in
[langgraph_agent.py](langgraph_agent.py).

## File breakdown

- [app.py](app.py) - API entry point, AgentKit wiring, and HTTP routes
- [langgraph_agent.py](langgraph_agent.py) - LangGraph graph definition and agent execution logic
- `index.html` - small browser UI for the demo
- `benchmark_scale.py` - runs concurrent inline vs queued benchmarks against the same agent and writes CSV output
- `plot_benchmark_results.py` - turns benchmark CSVs into PNG charts with pandas/matplotlib
- `artifacts/benchmark_sample/` - sample benchmark CSVs and charts checked into the repo

## Quickstart

```bash
uv sync
```

Create a `.env` file with your API key before you start the server or worker:

```bash
OPENAI_API_KEY=your-key-here
```

```bash
docker run -d -p 6379:6379 redis:8
```

Start the API:

```bash
uv run uvicorn app:app --reload
```

Start the worker in a second terminal:

```bash
uv run rak worker --name minimal_release_demo --tasks app:tasks
```

Open the demo:

```bash
open http://localhost:8000/demo
```

## Endpoints

- UI: `GET /demo`
- Task state: `GET /tasks/{task_id}`
- Task stream: `GET /tasks/{task_id}/stream`
- Task input: `POST /tasks/{task_id}/input`
- A2A discovery: `GET /.well-known/agent.json`
- OpenAPI docs: `GET /docs`
