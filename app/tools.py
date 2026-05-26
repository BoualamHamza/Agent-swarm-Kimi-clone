"""Tool schemas (OpenAI function-calling format) and the executor.

Sixteen tools are available to every worker agent:

  Pure-Python tools (always available):
    - calculate                 (sandboxed math via asteval)
    - get_current_date

  Swarm-memory tools (always available):
    - write_to_shared_memory / read_shared_memory / wait_for_memory

  Web (always available):
    - web_search                (Tavily — finds URLs + snippets)
    - scrape_url                (Firecrawl — full page content as markdown;
                                 requires FIRECRAWL_API_KEY)
    - map_website               (Firecrawl — discover a site's URLs via its
                                 sitemap; requires FIRECRAWL_API_KEY)

  Sandbox tools (require an injected SwarmSandbox; otherwise return
  "sandbox unavailable"):
    - run_python                (fresh interpreter per call — persist via files)
    - read_file / write_file / edit_file
    - list_files / glob_files / grep_files
    - run_shell

The executor returns a string — OpenAI requires ``tool`` message content
to be a string.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from asteval import Interpreter
from langsmith import traceable

from app.client import get_firecrawl, get_tavily
from app.memory import SharedMemoryStore
from app.sandbox import SwarmSandbox

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = "/home/user/workspace/artifacts"
_SANDBOX_UNAVAILABLE = (
    "Error: sandbox unavailable (no E2B_API_KEY set or sandbox creation failed)."
)

# Max chars returned by scrape_url / map_website before truncation. Raise for
# large-context models that can absorb full pages; env-configurable.
SCRAPE_MAX_CHARS = int(os.getenv("SCRAPE_MAX_CHARS", "40000"))
# Max lines read_file may return in a single call.
READ_FILE_MAX_LINES = int(os.getenv("READ_FILE_MAX_LINES", "15000"))


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
            "name": "wait_for_memory",
            "description": (
                "Block until another agent writes the given key to shared memory, "
                "then return its value. Use when your task explicitly depends on a "
                "finding another agent must produce first. Returns the stored value "
                "on success, or an error message if the timeout elapses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key":         {"type": "string",  "description": "Shared-memory key to wait for"},
                    "timeout_sec": {"type": "integer", "description": "Max seconds to wait (1-120, default 30)", "default": 30},
                },
                "required": ["key"],
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
    {
        "type": "function",
        "function": {
            "name": "scrape_url",
            "description": (
                "Fetch the full content of a web page as clean markdown using Firecrawl. "
                "Use this after web_search to read the actual content of a promising URL, "
                "or when you have a direct URL and need its full text rather than a snippet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to scrape, e.g. 'https://example.com/article'",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "map_website",
            "description": (
                "Discover the URLs of a website (sitemap-driven) without scraping their content. "
                "Use this to find which pages exist on a site before deciding what to scrape_url. "
                "Pass an optional 'search' to return only the most relevant URLs for a topic. "
                "Returns a ranked list of URL + title + description; then scrape_url the ones you want."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The root site URL to map, e.g. 'https://example.com'",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional topic filter; returns the most relevant URLs first, e.g. 'pricing'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max URLs to return (1-100, default 50)",
                        "default": 50,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute Python code in a secure E2B cloud sandbox. Each call runs in a FRESH "
                "Python interpreter; persist state by writing files to /home/user/workspace/. "
                "Returns stdout, stderr, and exit code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code":    {"type": "string",  "description": "Python source to run"},
                    "timeout": {"type": "integer", "description": "Per-call timeout in seconds (1-120, default 30)", "default": 30},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file from the shared sandbox filesystem. Returns up to `limit` "
                "lines starting at `offset`. Relative paths resolve under /home/user/."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":   {"type": "string",  "description": "File path, e.g. 'workspace/data.csv' or '/home/user/skills/python-runner/SKILL.md'"},
                    "offset": {"type": "integer", "description": "Line offset (default 0)", "default": 0},
                    "limit":  {"type": "integer", "description": "Max lines to return (default 2000)", "default": 2000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write (or overwrite) a text file in the shared sandbox filesystem. "
                "To produce a user-facing deliverable, save under /home/user/workspace/artifacts/."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "File path; relative resolves under /home/user/"},
                    "content": {"type": "string", "description": "File contents"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace text in an existing file. Returns the number of occurrences replaced.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":        {"type": "string",  "description": "File path"},
                    "old_string":  {"type": "string",  "description": "Exact text to find"},
                    "new_string":  {"type": "string",  "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false → first only)", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List entries in a sandbox directory. Defaults to /home/user/workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '/home/user/workspace')", "default": "/home/user/workspace"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Find files matching a glob pattern in the sandbox. Defaults to /home/user/workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.csv' or 'analysis_*.py'"},
                    "path":    {"type": "string", "description": "Root directory (default '/home/user/workspace')", "default": "/home/user/workspace"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": "Recursive substring search across sandbox files. Returns 'path:line:text' for each match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Substring to find"},
                    "path":    {"type": "string", "description": "Root directory (default '/home/user/workspace')", "default": "/home/user/workspace"},
                    "include": {"type": "string", "description": "Optional filename glob filter, e.g. '*.py'", "default": ""},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command inside the sandbox. Returns exit code, stdout, and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string",  "description": "Shell command, e.g. 'du -sh workspace' or 'mkdir -p workspace/output'"},
                    "timeout": {"type": "integer", "description": "Per-call timeout in seconds (1-300, default 60)", "default": 60},
                },
                "required": ["command"],
            },
        },
    },
]


# ─── Executor ────────────────────────────────────────────────────────────────


class ToolExecutor:
    """Stateful executor — holds shared memory, the write lock, the asteval
    interpreter, and an optional reference to the shared SwarmSandbox.

    The sandbox lifecycle is owned by the swarm conductor, NOT by this
    executor — multiple workers share the same sandbox.
    """

    def __init__(
        self,
        shared_memory: dict[str, str],
        lock: asyncio.Lock,
        *,
        store: SharedMemoryStore | None = None,
        session_id: str | None = None,
        sandbox: SwarmSandbox | None = None,
    ):
        self.shared_memory = shared_memory
        self.lock = lock
        # When both are set, write_to_shared_memory persists through to the store.
        self.store = store
        self.session_id = session_id
        # asteval is sandboxed: no imports, no exec, no attribute access.
        self._asteval = Interpreter(minimal=False, no_print=True)
        # Optional — None means sandbox-backed tools return an unavailable error.
        self.sandbox = sandbox

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
            if name == "wait_for_memory":
                return await self._wait_for_memory(
                    args.get("key", ""),
                    int(args.get("timeout_sec", 30)),
                )
            if name == "web_search":
                return await self._web_search(args.get("query", ""), int(args.get("max_results", 5)))
            if name == "scrape_url":
                return await self._scrape_url(args.get("url", ""))
            if name == "map_website":
                return await self._map_website(
                    args.get("url", ""),
                    args.get("search", ""),
                    int(args.get("limit", 50)),
                )
            if name == "run_python":
                return await self._run_python(args.get("code", ""), int(args.get("timeout", 30)))
            if name == "read_file":
                return await self._read_file(
                    args.get("path", ""),
                    int(args.get("offset", 0)),
                    int(args.get("limit", 2000)),
                )
            if name == "write_file":
                return await self._write_file(args.get("path", ""), args.get("content", ""))
            if name == "edit_file":
                return await self._edit_file(
                    args.get("path", ""),
                    args.get("old_string", ""),
                    args.get("new_string", ""),
                    bool(args.get("replace_all", False)),
                )
            if name == "list_files":
                return await self._list_files(args.get("path", "/home/user/workspace"))
            if name == "glob_files":
                return await self._glob_files(
                    args.get("pattern", ""),
                    args.get("path", "/home/user/workspace"),
                )
            if name == "grep_files":
                return await self._grep_files(
                    args.get("pattern", ""),
                    args.get("path", "/home/user/workspace"),
                    args.get("include", ""),
                )
            if name == "run_shell":
                return await self._run_shell(
                    args.get("command", ""),
                    int(args.get("timeout", 60)),
                )
            return f"Unknown tool: {name}"
        except Exception as e:  # surface tool errors as text — workers can recover
            return f"Error in {name}: {type(e).__name__}: {e}"

    # ─── Pure-Python tools ──────────────────────────────────────────────────

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
        if self.store is not None and self.session_id is not None:
            try:
                await self.store.put(self.session_id, key, value)
            except Exception as e:
                logger.warning(
                    "memory store write failed (session=%s, key=%r): %s",
                    self.session_id, key, e,
                )
        return f'Stored under key "{key}".'

    def _read_memory(self, key: str) -> str:
        if key == "all":
            if not self.shared_memory:
                return "(shared memory is empty)"
            return "\n".join(f"[{k}]: {v}" for k, v in self.shared_memory.items())
        return self.shared_memory.get(key, f'Nothing found for key "{key}".')

    async def _wait_for_memory(self, key: str, timeout_sec: int) -> str:
        """Poll the shared dict for ``key`` until it appears or the timeout
        elapses. Releases the lock between polls so writers can proceed.
        """
        if not key:
            return "Error: key is required"
        timeout_sec = max(1, min(120, timeout_sec))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_sec
        poll = 0.5
        while True:
            async with self.lock:
                if key in self.shared_memory:
                    return self.shared_memory[key]
            remaining = deadline - loop.time()
            if remaining <= 0:
                return (
                    f'Error: timed out after {timeout_sec}s waiting for '
                    f'shared-memory key "{key}". Either the upstream agent '
                    f"is still working or its task didn't write that key."
                )
            await asyncio.sleep(min(poll, remaining))

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

    async def _scrape_url(self, url: str) -> str:
        if not url.strip():
            return "Error: url is required"
        try:
            client = get_firecrawl()
        except RuntimeError as e:
            return f"Error: {e}"
        try:
            result = await asyncio.to_thread(
                client.scrape, url, formats=["markdown"]
            )
            markdown = getattr(result, "markdown", None) or ""
            if not markdown:
                return f"No content returned for {url}"
            # Cap to keep context manageable (env-configurable via SCRAPE_MAX_CHARS)
            if len(markdown) > SCRAPE_MAX_CHARS:
                markdown = markdown[:SCRAPE_MAX_CHARS] + "\n\n[…content truncated]"
            return markdown
        except Exception as e:
            return f"Error scraping {url}: {type(e).__name__}: {e}"

    async def _map_website(self, url: str, search: str, limit: int) -> str:
        if not url.strip():
            return "Error: url is required"
        try:
            client = get_firecrawl()
        except RuntimeError as e:
            return f"Error: {e}"
        limit = max(1, min(100, limit))
        search_filter = search.strip() or None
        try:
            result = await asyncio.to_thread(
                client.map, url, search=search_filter, limit=limit
            )
            links = getattr(result, "links", None) or []
            if not links:
                return f"No URLs found for {url}"
            header = (
                f'URLs on {url} (filtered by "{search_filter}"):'
                if search_filter
                else f"URLs on {url}:"
            )
            lines = [header]
            for i, link in enumerate(links, 1):
                link_url = getattr(link, "url", "") or ""
                title = getattr(link, "title", None) or "(no title)"
                desc = (getattr(link, "description", None) or "").replace("\n", " ")
                entry = f"{i}. {title}\n   {link_url}"
                if desc:
                    entry += f"\n   {desc[:200]}"
                lines.append(entry)
            out = "\n".join(lines)
            if len(out) > SCRAPE_MAX_CHARS:
                out = out[:SCRAPE_MAX_CHARS] + "\n\n[…list truncated]"
            return out
        except Exception as e:
            return f"Error mapping {url}: {type(e).__name__}: {e}"

    # ─── Sandbox-backed tools ───────────────────────────────────────────────

    async def _run_python(self, code: str, timeout: int) -> str:
        if not code.strip():
            return "Error: empty code"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        timeout = max(1, min(120, timeout))
        out = await self.sandbox.run_python(code, timeout=timeout)
        return _format_exec(out)

    async def _read_file(self, path: str, offset: int, limit: int) -> str:
        if not path.strip():
            return "Error: path is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        offset = max(0, offset)
        limit = max(1, min(READ_FILE_MAX_LINES, limit))
        text = await self.sandbox.read(path, offset=offset, limit=limit)
        return text if text else "(file is empty)"

    async def _write_file(self, path: str, content: str) -> str:
        if not path.strip():
            return "Error: path is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        abs_path = await self.sandbox.write(path, content)
        # Artifact memory bridge — if the file lands under the artifacts dir,
        # surface it via shared memory so later workers see the manifest.
        if abs_path.startswith(_ARTIFACTS_DIR + "/"):
            filename = os.path.basename(abs_path)
            ext = os.path.splitext(filename)[1].lstrip(".") or "file"
            try:
                await self._write_memory(f"artifact:{filename}", f"{ext} saved to {abs_path}")
            except Exception:
                pass
        return f"Wrote {abs_path}"

    async def _edit_file(
        self, path: str, old: str, new: str, replace_all: bool
    ) -> str:
        if not path.strip():
            return "Error: path is required"
        if not old:
            return "Error: old_string is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        result = await self.sandbox.edit(path, old, new, replace_all=replace_all)
        return f"Edited {result['path']}: {result['occurrences']} occurrence(s)"

    async def _list_files(self, path: str) -> str:
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        entries = await self.sandbox.ls(path or "/home/user/workspace")
        if not entries:
            return f"(no entries in {path or '/home/user/workspace'})"
        lines: list[str] = []
        for e in entries:
            tag = "[D]" if e["is_dir"] else "[F]"
            size = f"{e['size']}b" if not e["is_dir"] else "-"
            lines.append(f"{tag} {e['name']:32}  {size:>10}  {e['path']}")
        return "\n".join(lines)

    async def _glob_files(self, pattern: str, path: str) -> str:
        if not pattern.strip():
            return "Error: pattern is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        matches = await self.sandbox.glob(pattern, path or "/home/user/workspace")
        if not matches:
            return f'(no matches for "{pattern}" under {path or "/home/user/workspace"})'
        return "\n".join(matches)

    async def _grep_files(self, pattern: str, path: str, include: str) -> str:
        if not pattern.strip():
            return "Error: pattern is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        matches = await self.sandbox.grep(
            pattern, path or "/home/user/workspace", include=include or "",
        )
        if not matches:
            return f'(no matches for "{pattern}")'
        return "\n".join(f"{m['path']}:{m['line']}:{m['text']}" for m in matches)

    async def _run_shell(self, command: str, timeout: int) -> str:
        if not command.strip():
            return "Error: command is required"
        if self.sandbox is None:
            return _SANDBOX_UNAVAILABLE
        timeout = max(1, min(300, timeout))
        out = await self.sandbox.execute(command, timeout=timeout)
        return _format_exec(out)

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Reset asteval state. The sandbox lifecycle is owned by the
        conductor, NOT by this executor. Idempotent.
        """
        # Clear asteval symbol table so each worker starts fresh after close.
        try:
            self._asteval.symtable.clear()  # type: ignore[attr-defined]
        except Exception:
            pass


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _format_exec(out: dict) -> str:
    """Format an ``execute``/``run_python`` result dict into a single string."""
    parts: list[str] = [f"exit={out.get('exit_code', 0)}"]
    stdout = (out.get("stdout") or "").rstrip()
    stderr = (out.get("stderr") or "").rstrip()
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if not stdout and not stderr:
        parts.append("(no output)")
    return "\n".join(parts)
