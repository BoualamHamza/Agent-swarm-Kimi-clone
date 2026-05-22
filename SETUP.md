# Setup

This guide walks you through getting Agent Swarm running on your machine, from cloning the repo to your first swarm run.

## Prerequisites

You need Python 3.11 or newer. Python 3.12 is what the project is developed against, so it is the safest choice. Check what you have:

```bash
python3 --version
```

You will also need API keys for a few services. The swarm talks to language models through OpenRouter, searches the web through Tavily, scrapes pages through Firecrawl, and runs code in sandboxes through E2B. Sign up for each and grab a key:

- OpenRouter for model access
- Tavily for web search
- Firecrawl for page scraping
- E2B for the code sandbox

LangSmith is optional. It gives you tracing if you want to see what every agent did, but the swarm runs fine without it.

## Install

Clone the repo and move into it, then create a virtual environment so the dependencies stay isolated from the rest of your system.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows the activate command is `.venv\Scripts\activate` instead.

Install the project in editable mode. This pulls in every runtime dependency and registers the `agent-swarm` command.

```bash
pip install -e .
```

If you plan to run the test suite or work on the code, install the dev extras as well:

```bash
pip install -e ".[dev]"
```

## Configure your environment

Copy the example environment file and fill in your own keys.

```bash
cp .env.example .env
```

Open `.env` in your editor. The first four keys are required:

```
OPENROUTER_API_KEY=sk-or-v1-...
TAVILY_API_KEY=tvly-...
E2B_API_KEY=e2b_...
FIRECRAWL_API_KEY=fc-...
```

The rest are optional. Uncomment and set the LangSmith block if you want tracing. The memory backend defaults to in-memory, which is fine for most runs. Switch it to `sqlite` if you want shared memory to survive across runs:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=agent-swarm

SWARM_MEMORY_BACKEND=inmemory
SWARM_MEMORY_PATH=swarm_memory.db
```

## Build the sandbox template

Workers run Python, shell commands, and file operations inside an E2B sandbox. The sandbox uses a custom template that ships with pandas, matplotlib, LibreOffice, and the other tools the skills depend on. You build this template once per environment.

```bash
python scripts/build_e2b_template.py
```

The build takes a few minutes the first time because it downloads the Python base image and installs every package. When it finishes it prints a template id. Copy that line into your `.env`:

```
E2B_TEMPLATE_ID=...
```

If you skip this step the swarm still runs, but it falls back to E2B's default sandbox, which is missing the heavier tools that the data and document skills rely on.

## Run it

The terminal UI is the main way to use the swarm. Launch it and type a task:

```bash
agent-swarm
```

You will see named agents spawn, call tools, write to shared memory, and converge on a final answer. Press `q` to quit.

If you just want to see how it behaves without spending any API credits, run the scripted demo. It needs no keys at all:

```bash
agent-swarm --demo
```

## Run it as an API

There is also a FastAPI server that streams swarm events over Server-Sent Events. This is what you would use to wire the swarm into another application.

```bash
uvicorn app.api:app --reload
```

POST a task to `/run` and read the event stream back, or hit `/health` to check the server is up.

## Run the tests

With the dev extras installed:

```bash
pytest
```

## Tuning and models

The default models for the orchestrator and workers live in `app/models.py`. Edit that dictionary to switch models, or override per call with the `model=` argument.

There are also caps on how many sub-agents can spawn, how many tool calls each worker can make, and how many agents run in parallel. These exist to keep costs bounded. If you want to push the swarm harder, adjust them in `app/orchestrator.py` and `app/loop.py`.
