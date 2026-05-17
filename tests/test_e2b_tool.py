"""Tests for ToolExecutor's sandbox-backed tools.

A fake SwarmSandbox is injected so we never touch the real e2b API.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


# ─── Fake SwarmSandbox ───────────────────────────────────────────────────────


class FakeSandbox:
    """Records every call. Each method returns whatever the caller pre-loaded
    into ``self.next_*`` or a sensible default."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.next_read: str = ""
        self.next_run_python: dict = {"stdout": "", "stderr": "", "exit_code": 0}
        self.next_execute: dict = {"stdout": "", "stderr": "", "exit_code": 0}
        self.next_ls: list[dict] = []
        self.next_glob: list[str] = []
        self.next_grep: list[dict] = []
        self.next_edit: dict = {"path": "", "occurrences": 0}
        self.next_write_path: str = ""
        self.raise_next: BaseException | None = None

    def _record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))
        if self.raise_next is not None:
            exc, self.raise_next = self.raise_next, None
            raise exc

    async def run_python(self, code: str, *, timeout: int = 30) -> dict:
        self._record("run_python", code, timeout=timeout)
        return self.next_run_python

    async def execute(self, command: str, *, timeout: int = 60) -> dict:
        self._record("execute", command, timeout=timeout)
        return self.next_execute

    async def read(self, path: str, *, offset: int = 0, limit: int = 2000) -> str:
        self._record("read", path, offset=offset, limit=limit)
        return self.next_read

    async def write(self, path: str, content: str) -> str:
        self._record("write", path, content)
        return self.next_write_path or (
            path if path.startswith("/") else f"/home/user/{path}"
        )

    async def edit(self, path: str, old: str, new: str, *, replace_all: bool = False) -> dict:
        self._record("edit", path, old, new, replace_all=replace_all)
        return self.next_edit or {"path": path, "occurrences": 1}

    async def ls(self, path: str = "") -> list[dict]:
        self._record("ls", path)
        return self.next_ls

    async def glob(self, pattern: str, path: str = "") -> list[str]:
        self._record("glob", pattern, path)
        return self.next_glob

    async def grep(self, pattern: str, path: str = "", *, include: str = "") -> list[dict]:
        self._record("grep", pattern, path, include=include)
        return self.next_grep


def _executor(sandbox: FakeSandbox | None) -> Any:
    from app.tools import ToolExecutor
    return ToolExecutor({}, asyncio.Lock(), sandbox=sandbox)  # type: ignore[arg-type]


# ─── Schema registration ─────────────────────────────────────────────────────


def test_all_schemas_registered():
    from app.tools import TOOL_SCHEMAS

    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    expected = {
        "calculate", "get_current_date",
        "write_to_shared_memory", "read_shared_memory", "wait_for_memory",
        "request_handoff", "web_search", "scrape_url",
        "run_python",
        "read_file", "write_file", "edit_file",
        "list_files", "glob_files", "grep_files", "run_shell",
    }
    assert names == expected


# ─── run_python ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_python_routes_to_sandbox():
    sb = FakeSandbox()
    sb.next_run_python = {"stdout": "hello\n", "stderr": "", "exit_code": 0}
    ex = _executor(sb)
    out = await ex.execute("run_python", {"code": "print('hello')"})
    assert "hello" in out
    assert "exit=0" in out
    assert sb.calls[0][0] == "run_python"
    assert sb.calls[0][1][0] == "print('hello')"


@pytest.mark.asyncio
async def test_run_python_clamps_timeout():
    sb = FakeSandbox()
    ex = _executor(sb)
    await ex.execute("run_python", {"code": "1", "timeout": 0})
    await ex.execute("run_python", {"code": "2", "timeout": 9999})
    assert sb.calls[0][2]["timeout"] == 1
    assert sb.calls[1][2]["timeout"] == 120


@pytest.mark.asyncio
async def test_run_python_empty_code_short_circuits():
    sb = FakeSandbox()
    ex = _executor(sb)
    out = await ex.execute("run_python", {"code": "   "})
    assert "empty code" in out.lower()
    assert sb.calls == []  # never reached the sandbox


@pytest.mark.asyncio
async def test_sandbox_unavailable_when_none():
    """Every sandbox-backed tool must return the unavailable message when
    no sandbox is injected (covers soft-fail when E2B_API_KEY is missing)."""
    ex = _executor(None)
    for tool, args in [
        ("run_python", {"code": "1"}),
        ("read_file", {"path": "x.txt"}),
        ("write_file", {"path": "x.txt", "content": "x"}),
        ("edit_file", {"path": "x.txt", "old_string": "a", "new_string": "b"}),
        ("list_files", {}),
        ("glob_files", {"pattern": "*.py"}),
        ("grep_files", {"pattern": "foo"}),
        ("run_shell", {"command": "ls"}),
    ]:
        out = await ex.execute(tool, args)
        assert "sandbox unavailable" in out.lower(), f"{tool} did not soft-fail"


# ─── Filesystem tools ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_routes_to_sandbox_read():
    sb = FakeSandbox()
    sb.next_read = "line one\nline two\n"
    ex = _executor(sb)
    out = await ex.execute("read_file", {"path": "notes.txt", "offset": 1, "limit": 100})
    assert "line one" in out
    assert sb.calls[0][0] == "read"
    assert sb.calls[0][2]["offset"] == 1
    assert sb.calls[0][2]["limit"] == 100


@pytest.mark.asyncio
async def test_write_file_returns_abs_path():
    sb = FakeSandbox()
    sb.next_write_path = "/home/user/notes.txt"
    ex = _executor(sb)
    out = await ex.execute("write_file", {"path": "notes.txt", "content": "hi"})
    assert "/home/user/notes.txt" in out
    assert sb.calls[0][0] == "write"


@pytest.mark.asyncio
async def test_write_file_under_artifacts_writes_to_shared_memory():
    sb = FakeSandbox()
    sb.next_write_path = "/home/user/workspace/artifacts/chart.png"
    ex = _executor(sb)
    await ex.execute("write_file", {"path": "workspace/artifacts/chart.png", "content": "x"})
    # Shared memory should now contain a manifest entry
    assert any(k.startswith("artifact:chart.png") for k in ex.shared_memory.keys())


@pytest.mark.asyncio
async def test_edit_file_reports_occurrences():
    sb = FakeSandbox()
    sb.next_edit = {"path": "/home/user/a.txt", "occurrences": 3}
    ex = _executor(sb)
    out = await ex.execute(
        "edit_file",
        {"path": "a.txt", "old_string": "x", "new_string": "y", "replace_all": True},
    )
    assert "3 occurrence" in out
    assert sb.calls[0][2]["replace_all"] is True


@pytest.mark.asyncio
async def test_list_files_renders_entries():
    sb = FakeSandbox()
    sb.next_ls = [
        {"name": "data", "path": "/home/user/workspace/data", "is_dir": True, "size": 0, "modified_at": ""},
        {"name": "out.csv", "path": "/home/user/workspace/out.csv", "is_dir": False, "size": 42, "modified_at": ""},
    ]
    ex = _executor(sb)
    out = await ex.execute("list_files", {})
    assert "[D] data" in out
    assert "[F] out.csv" in out
    assert "42b" in out


@pytest.mark.asyncio
async def test_glob_files_returns_matches_joined():
    sb = FakeSandbox()
    sb.next_glob = ["/home/user/workspace/a.py", "/home/user/workspace/b.py"]
    ex = _executor(sb)
    out = await ex.execute("glob_files", {"pattern": "*.py"})
    assert "/home/user/workspace/a.py" in out
    assert "/home/user/workspace/b.py" in out


@pytest.mark.asyncio
async def test_grep_files_returns_path_line_text():
    sb = FakeSandbox()
    sb.next_grep = [
        {"path": "/home/user/workspace/a.py", "line": 7, "text": "import os"},
    ]
    ex = _executor(sb)
    out = await ex.execute("grep_files", {"pattern": "import"})
    assert "/home/user/workspace/a.py:7:import os" in out


@pytest.mark.asyncio
async def test_run_shell_returns_exit_and_streams():
    sb = FakeSandbox()
    sb.next_execute = {"stdout": "ok\n", "stderr": "warn\n", "exit_code": 0}
    ex = _executor(sb)
    out = await ex.execute("run_shell", {"command": "echo ok"})
    assert "exit=0" in out
    assert "ok" in out
    assert "warn" in out


# ─── Error surfacing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_errors_become_text():
    """When the sandbox raises, the executor catches and returns it as text
    so the worker can recover."""
    sb = FakeSandbox()
    sb.raise_next = RuntimeError("sandbox died")
    ex = _executor(sb)
    out = await ex.execute("run_python", {"code": "1"})
    assert "error" in out.lower()
    assert "sandbox died" in out


# ─── close() ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_does_not_kill_sandbox():
    """The executor no longer owns the sandbox lifecycle. close() resets
    asteval but must NOT kill the shared sandbox."""
    sb = FakeSandbox()
    ex = _executor(sb)
    await ex.execute("run_python", {"code": "1"})
    await ex.close()
    # No "kill" should ever have been called — FakeSandbox doesn't even
    # implement it, which would have raised AttributeError if attempted.
    assert all(c[0] != "kill" for c in sb.calls)
