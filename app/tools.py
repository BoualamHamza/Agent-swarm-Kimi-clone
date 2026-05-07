"""Tool schemas (OpenAI function-calling format) and the executor.

Six tools are available to every worker agent:
  - calculate            (sandboxed math via asteval)
  - get_current_date
  - write_to_shared_memory / read_shared_memory   (the swarm communication backbone)
  - request_handoff      (dynamic specialist spawn)
  - web_search           (Tavily)

The executor returns a string — OpenAI requires `tool` message content to be a string.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from asteval import Interpreter
from langsmith import traceable

from app.client import get_tavily

# ─── Schemas (OpenAI function-calling format) ────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression and return the numeric result. Supports basic arithmetic, sqrt, sin, cos, log, pi, e, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A math expression, e.g. '2 * pi * 5' or 'sqrt(144) + 3'",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "Return the current date and time in ISO 8601 format.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_to_shared_memory",
            "description": "Store a finding in shared swarm memory so ALL other agents can read it. Use short descriptive keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key":   {"type": "string", "description": "Short descriptive label, e.g. 'market_size'"},
                    "value": {"type": "string", "description": "The information to store"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_shared_memory",
            "description": "Read findings written by other swarm agents. Use key='all' to retrieve everything stored.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Specific key, or 'all' for the full memory dump"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_handoff",
            "description": "Signal that a different specialist agent should handle a sub-problem you discovered. Only use if the work genuinely needs a different specialization than yours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_role": {"type": "string", "description": "Type of specialist needed"},
                    "reason":  {"type": "string", "description": "Why this needs a different specialist"},
                    "context": {"type": "string", "description": "Everything the new agent needs to know"},
                },
                "required": ["to_role", "reason", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information using Tavily. Returns top results with title, url, and a snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "How many results to return (1-10)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
]


# ─── Executor ────────────────────────────────────────────────────────────────


class ToolExecutor:
    """Stateful executor — holds shared memory, the write lock, and the asteval interpreter."""

    def __init__(self, shared_memory: dict[str, str], lock: asyncio.Lock):
        self.shared_memory = shared_memory
        self.lock = lock
        # asteval is sandboxed: no imports, no exec, no attribute access.
        self._asteval = Interpreter(minimal=False, no_print=True)

    @traceable(run_type="tool")
    async def execute(self, name: str, args: dict[str, Any]) -> str:
        # Each tool call appears as a `tool`-type run in LangSmith. The tool name
        # is in the inputs (`name`, `args`); the run itself is named "execute".
        try:
            if name == "calculate":
                return self._calculate(args.get("expression", ""))
            if name == "get_current_date":
                return datetime.now().astimezone().isoformat(timespec="seconds")
            if name == "write_to_shared_memory":
                return await self._write_memory(args.get("key", ""), args.get("value", ""))
            if name == "read_shared_memory":
                return self._read_memory(args.get("key", ""))
            if name == "request_handoff":
                return f'Handoff to "{args.get("to_role", "?")}" registered.'
            if name == "web_search":
                return await self._web_search(args.get("query", ""), int(args.get("max_results", 5)))
            return f"Unknown tool: {name}"
        except Exception as e:  # surface tool errors as text — workers can recover
            return f"Error in {name}: {type(e).__name__}: {e}"

    # ─── Individual tools ────────────────────────────────────────────────────

    def _calculate(self, expression: str) -> str:
        if not expression.strip():
            return "Error: empty expression"
        result = self._asteval(expression)
        if self._asteval.error:
            err = "; ".join(e.get_error()[1] for e in self._asteval.error)
            self._asteval.error = []  # clear for next call
            return f"Error: {err}"
        return f"{expression} = {result}"

    async def _write_memory(self, key: str, value: str) -> str:
        if not key:
            return "Error: key is required"
        async with self.lock:
            self.shared_memory[key] = value
        return f'Stored under key "{key}".'

    def _read_memory(self, key: str) -> str:
        if key == "all":
            if not self.shared_memory:
                return "(shared memory is empty)"
            return "\n".join(f"[{k}]: {v}" for k, v in self.shared_memory.items())
        return self.shared_memory.get(key, f'Nothing found for key "{key}".')

    async def _web_search(self, query: str, max_results: int) -> str:
        if not query.strip():
            return "Error: query is required"
        max_results = max(1, min(10, max_results))
        client = get_tavily()
        res = await client.search(query=query, max_results=max_results)
        results = res.get("results", [])
        if not results:
            return f'No results for "{query}".'
        lines = [f'Search results for "{query}":']
        for i, r in enumerate(results, 1):
            title   = r.get("title", "(no title)")
            url     = r.get("url", "")
            snippet = (r.get("content", "") or "")[:300].replace("\n", " ")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        return "\n".join(lines)
