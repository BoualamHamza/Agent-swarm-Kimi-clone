"""Tests for app.sandbox.SwarmSandbox.

The underlying e2b AsyncSandbox is stubbed — we never hit the real API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from e2b import FileType


# ─── Stub e2b AsyncSandbox ───────────────────────────────────────────────────


class _StubFiles:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.write_calls: list[tuple[str, Any]] = []
        self.list_calls: list[str] = []
        self.read_calls: list[tuple[str, str]] = []
        self.make_dir_calls: list[str] = []
        # When set, controls what list() returns for any path
        self.list_result: list[Any] | None = None

    async def write(self, path: str, data: Any, **_: Any) -> None:
        self.write_calls.append((path, data))
        self.store[path] = data

    async def read(self, path: str, format: str = "text", **_: Any) -> Any:
        self.read_calls.append((path, format))
        if path not in self.store:
            raise FileNotFoundError(path)
        val = self.store[path]
        if format == "bytes":
            return val if isinstance(val, bytes) else str(val).encode("utf-8")
        return val if isinstance(val, str) else (val.decode() if isinstance(val, bytes) else str(val))

    async def list(self, path: str, **_: Any) -> list[Any]:
        self.list_calls.append(path)
        if self.list_result is not None:
            return self.list_result
        return []

    async def make_dir(self, path: str, **_: Any) -> bool:
        self.make_dir_calls.append(path)
        return True


class _StubCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float | None]] = []
        # Mapping of substring -> (stdout, stderr, exit_code). First match wins.
        self.responses: list[tuple[str, str, str, int]] = []
        self.default = ("", "", 0)

    async def run(self, cmd: str, *, timeout: float | None = None, **_: Any) -> Any:
        self.calls.append((cmd, timeout))
        for needle, stdout, stderr, code in self.responses:
            if needle in cmd:
                return SimpleNamespace(stdout=stdout, stderr=stderr, exit_code=code)
        stdout, stderr, code = self.default
        return SimpleNamespace(stdout=stdout, stderr=stderr, exit_code=code)


class StubAsyncSandbox:
    def __init__(self) -> None:
        self.files = _StubFiles()
        self.commands = _StubCommands()
        self.killed = False

    async def kill(self) -> None:
        self.killed = True


def _entry(name: str, *, is_dir: bool = False, size: int = 0, path: str | None = None) -> Any:
    """Build something duck-typed like e2b.EntryInfo."""
    return SimpleNamespace(
        name=name,
        path=path or f"/home/user/{name}",
        type=FileType.DIR if is_dir else FileType.FILE,
        size=size,
        mode=0o644,
        permissions="rw-r--r--",
        owner="user",
        group="user",
        modified_time=datetime(2026, 5, 12, tzinfo=timezone.utc),
        symlink_target=None,
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


def _make_sandbox(stub: StubAsyncSandbox):
    from app.sandbox import SwarmSandbox
    return SwarmSandbox(stub)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_resolve_relative_paths_against_root():
    stub = StubAsyncSandbox()
    sb = _make_sandbox(stub)
    await sb.write("workspace/data.csv", "a,b,c\n")
    assert ("/home/user/workspace/data.csv", "a,b,c\n") in stub.files.write_calls


@pytest.mark.asyncio
async def test_resolve_absolute_paths_unchanged():
    stub = StubAsyncSandbox()
    sb = _make_sandbox(stub)
    await sb.write("/tmp/foo.txt", "x")
    assert ("/tmp/foo.txt", "x") in stub.files.write_calls


@pytest.mark.asyncio
async def test_ls_returns_dicts_with_is_dir_flag():
    stub = StubAsyncSandbox()
    stub.files.list_result = [
        _entry("workspace", is_dir=True, path="/home/user/workspace"),
        _entry("notes.txt", size=12, path="/home/user/notes.txt"),
    ]
    sb = _make_sandbox(stub)
    entries = await sb.ls("")
    assert len(entries) == 2
    assert entries[0]["is_dir"] is True
    assert entries[0]["name"] == "workspace"
    assert entries[1]["is_dir"] is False
    assert entries[1]["size"] == 12


@pytest.mark.asyncio
async def test_read_paginates_by_lines():
    stub = StubAsyncSandbox()
    stub.files.store["/home/user/big.txt"] = "\n".join(f"line {i}" for i in range(10)) + "\n"
    sb = _make_sandbox(stub)
    text = await sb.read("big.txt", offset=2, limit=3)
    assert text == "line 2\nline 3\nline 4\n"


@pytest.mark.asyncio
async def test_read_bytes_returns_bytes():
    stub = StubAsyncSandbox()
    stub.files.store["/home/user/blob.bin"] = b"\x89PNG\r\n"
    sb = _make_sandbox(stub)
    data = await sb.read_bytes("blob.bin")
    assert data == b"\x89PNG\r\n"


@pytest.mark.asyncio
async def test_write_returns_absolute_path():
    stub = StubAsyncSandbox()
    sb = _make_sandbox(stub)
    p = await sb.write("hello.txt", "hi")
    assert p == "/home/user/hello.txt"


@pytest.mark.asyncio
async def test_edit_first_occurrence():
    stub = StubAsyncSandbox()
    stub.files.store["/home/user/a.txt"] = "foo bar foo"
    sb = _make_sandbox(stub)
    result = await sb.edit("a.txt", "foo", "BAZ", replace_all=False)
    assert result == {"path": "/home/user/a.txt", "occurrences": 1}
    assert stub.files.store["/home/user/a.txt"] == "BAZ bar foo"


@pytest.mark.asyncio
async def test_edit_replace_all_counts_occurrences():
    stub = StubAsyncSandbox()
    stub.files.store["/home/user/a.txt"] = "foo foo foo"
    sb = _make_sandbox(stub)
    result = await sb.edit("a.txt", "foo", "BAZ", replace_all=True)
    assert result == {"path": "/home/user/a.txt", "occurrences": 3}
    assert stub.files.store["/home/user/a.txt"] == "BAZ BAZ BAZ"


@pytest.mark.asyncio
async def test_edit_missing_string_raises():
    stub = StubAsyncSandbox()
    stub.files.store["/home/user/a.txt"] = "hello"
    sb = _make_sandbox(stub)
    with pytest.raises(ValueError):
        await sb.edit("a.txt", "absent", "x")


@pytest.mark.asyncio
async def test_glob_invokes_find_with_pattern():
    stub = StubAsyncSandbox()
    stub.commands.responses = [(
        "find", "/home/user/workspace/a.csv\n/home/user/workspace/b.csv", "", 0,
    )]
    sb = _make_sandbox(stub)
    matches = await sb.glob("*.csv", "workspace")
    assert matches == ["/home/user/workspace/a.csv", "/home/user/workspace/b.csv"]
    cmd, _ = stub.commands.calls[-1]
    assert "find /home/user/workspace" in cmd
    assert "-name '*.csv'" in cmd


@pytest.mark.asyncio
async def test_grep_parses_path_line_text():
    stub = StubAsyncSandbox()
    stub.commands.responses = [(
        "grep",
        "/home/user/workspace/a.py:12:hello\n/home/user/workspace/b.py:1:hello world",
        "",
        0,
    )]
    sb = _make_sandbox(stub)
    matches = await sb.grep("hello", "workspace")
    assert matches == [
        {"path": "/home/user/workspace/a.py", "line": 12, "text": "hello"},
        {"path": "/home/user/workspace/b.py", "line": 1, "text": "hello world"},
    ]


@pytest.mark.asyncio
async def test_execute_returns_exit_code():
    stub = StubAsyncSandbox()
    stub.commands.responses = [("ls", "a\nb", "", 0)]
    sb = _make_sandbox(stub)
    out = await sb.execute("ls /tmp", timeout=10)
    assert out == {"stdout": "a\nb", "stderr": "", "exit_code": 0}


@pytest.mark.asyncio
async def test_run_python_writes_temp_and_runs():
    stub = StubAsyncSandbox()
    stub.commands.responses = [("python", "42\n", "", 0)]
    sb = _make_sandbox(stub)
    out = await sb.run_python("print(42)", timeout=5)
    assert out["stdout"] == "42\n"
    assert out["exit_code"] == 0
    # A temp script was written under /tmp/_swarm_run_<uuid>.py
    written = [p for p, _ in stub.files.write_calls if p.startswith("/tmp/_swarm_run_")]
    assert len(written) == 1
    # The python command was invoked on that temp path
    py_cmd = next(c for c, _ in stub.commands.calls if c.startswith("python "))
    assert written[0] in py_cmd


@pytest.mark.asyncio
async def test_close_kills_underlying_sandbox():
    stub = StubAsyncSandbox()
    sb = _make_sandbox(stub)
    await sb.close()
    assert stub.killed is True


@pytest.mark.asyncio
async def test_close_is_idempotent():
    stub = StubAsyncSandbox()
    sb = _make_sandbox(stub)
    await sb.close()
    await sb.close()  # must not raise
    assert stub.killed is True


@pytest.mark.asyncio
async def test_list_files_swallows_missing_dir():
    """list_files exists for the artifact harvester — must not raise if the
    artifacts dir hasn't been created yet."""

    class BadFiles(_StubFiles):
        async def list(self, path: str, **_: Any) -> list[Any]:  # noqa: ARG002
            raise RuntimeError("dir not found")

    stub = StubAsyncSandbox()
    stub.files = BadFiles()
    sb = _make_sandbox(stub)
    assert await sb.list_files("workspace/artifacts") == []
