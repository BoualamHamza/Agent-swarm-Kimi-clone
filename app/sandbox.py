"""Async wrapper around a single shared `e2b.AsyncSandbox`.

One `SwarmSandbox` is created per swarm run and shared across all workers
(including handoff agents). All filesystem operations resolve relative paths
against ``/home/user`` so agents can use short paths like
``workspace/data.csv`` and still hit the right place.

The 4 parallel workers each call methods on the same sandbox; HTTPX (which
backs e2b's AsyncClient) is safe for concurrent requests, so the only lock
this wrapper needs is around ``edit`` — read-modify-write under contention
can silently drop concurrent edits otherwise.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from e2b import AsyncSandbox, FileType


_DEFAULT_ROOT = "/home/user"
# Sandbox lifetime in seconds. Public so the swarm bootstrap can use it as the
# single source of truth (overridable via the E2B_SANDBOX_TIMEOUT env var).
DEFAULT_SANDBOX_TIMEOUT = 3600


class SwarmSandbox:
    """Thin async facade over ``e2b.AsyncSandbox`` mirroring the operations
    DeepAgents exposes (ls/read/write/edit/glob/grep/execute/upload).
    """

    def __init__(self, sandbox: AsyncSandbox, root: str = _DEFAULT_ROOT) -> None:
        self._sandbox = sandbox
        self._root = root
        self._edit_lock = asyncio.Lock()

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        *,
        template_id: Optional[str] = None,
        timeout: int = DEFAULT_SANDBOX_TIMEOUT,
        root: str = _DEFAULT_ROOT,
    ) -> "SwarmSandbox":
        """Spin up a fresh sandbox. If ``template_id`` is None, e2b uses its
        default Python image (no skills directory exists yet — caller must
        create one before uploading skills).
        """
        if template_id:
            sb = await AsyncSandbox.create(template=template_id, timeout=timeout)
        else:
            sb = await AsyncSandbox.create(timeout=timeout)
        # Make sure workspace/artifacts/skills exist regardless of template —
        # the default image has no /home/user/workspace.
        for sub in ("workspace", "workspace/artifacts", "skills"):
            try:
                await sb.files.make_dir(f"{root}/{sub}")
            except Exception:
                pass
        return cls(sb, root=root)

    async def close(self) -> None:
        """Kill the underlying sandbox. Idempotent."""
        try:
            await self._sandbox.kill()
        except Exception:
            pass

    # ─── Path resolution ────────────────────────────────────────────────────

    def _resolve(self, path: str) -> str:
        if not path:
            return self._root
        if os.path.isabs(path):
            return path
        return os.path.join(self._root, path)

    # ─── Filesystem operations ──────────────────────────────────────────────

    async def ls(self, path: str = "") -> list[dict]:
        """List entries in a directory. Returns a list of dicts with
        ``path``, ``name``, ``is_dir``, ``size``, ``modified_at`` keys.
        """
        resolved = self._resolve(path)
        entries = await self._sandbox.files.list(resolved)
        out: list[dict] = []
        for e in entries:
            modified = ""
            if e.modified_time is not None:
                try:
                    modified = e.modified_time.isoformat()
                except Exception:
                    modified = ""
            out.append({
                "path": e.path,
                "name": e.name,
                "is_dir": e.type == FileType.DIR,
                "size": e.size,
                "modified_at": modified,
            })
        return out

    async def read(self, path: str, *, offset: int = 0, limit: int = 2000) -> str:
        """Read a file as text, line-paginated."""
        resolved = self._resolve(path)
        content = await self._sandbox.files.read(resolved, format="text")
        if not isinstance(content, str):
            content = str(content)
        lines = content.splitlines(keepends=True)
        return "".join(lines[offset: offset + limit])

    async def read_bytes(self, path: str) -> bytes:
        """Read a file as raw bytes — used for artifact download."""
        resolved = self._resolve(path)
        data = await self._sandbox.files.read(resolved, format="bytes")
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("utf-8")
        # Stream-ish fallback
        return bytes(data)  # type: ignore[arg-type]

    async def write(self, path: str, content: str) -> str:
        """Write text content. Returns the absolute path."""
        resolved = self._resolve(path)
        await self._sandbox.files.write(resolved, content)
        return resolved

    async def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> dict:
        """Replace a substring in a file. Returns ``{"path", "occurrences"}``
        or raises if the string is not found.
        """
        resolved = self._resolve(path)
        async with self._edit_lock:
            current = await self._sandbox.files.read(resolved, format="text")
            if not isinstance(current, str):
                current = str(current)
            count = current.count(old_string)
            if count == 0:
                raise ValueError(f"String not found in {resolved}")
            if replace_all:
                updated = current.replace(old_string, new_string)
                occurrences = count
            else:
                updated = current.replace(old_string, new_string, 1)
                occurrences = 1
            await self._sandbox.files.write(resolved, updated)
        return {"path": resolved, "occurrences": occurrences}

    async def glob(self, pattern: str, path: str = "") -> list[str]:
        """Find files matching a glob pattern (delegates to ``find`` in the
        sandbox)."""
        resolved = self._resolve(path) if path else self._root
        # Escape single quotes in the pattern to keep the shell happy.
        safe_pattern = pattern.replace("'", "'\\''")
        cmd = f"find {resolved} -name '{safe_pattern}' -type f 2>/dev/null"
        result = await self._sandbox.commands.run(cmd, timeout=20)
        return [p for p in (result.stdout or "").strip().splitlines() if p]

    async def grep(
        self,
        pattern: str,
        path: str = "",
        *,
        include: str = "",
    ) -> list[dict]:
        """Recursive grep. Returns a list of ``{"path", "line", "text"}``."""
        search_path = self._resolve(path) if path else self._root
        safe_pat = pattern.replace("'", "'\\''")
        cmd = f"grep -rn --fixed-strings '{safe_pat}' {search_path}"
        if include:
            safe_inc = include.replace("'", "'\\''")
            cmd += f" --include='{safe_inc}'"
        cmd += " 2>/dev/null"
        result = await self._sandbox.commands.run(cmd, timeout=30)
        matches: list[dict] = []
        for line in (result.stdout or "").strip().splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3:
                try:
                    line_no = int(parts[1])
                except ValueError:
                    continue
                matches.append(
                    {"path": parts[0], "line": line_no, "text": parts[2]})
        return matches

    async def execute(self, command: str, *, timeout: int = 60) -> dict:
        """Run a shell command. Returns ``{"stdout", "stderr", "exit_code"}``."""
        result = await self._sandbox.commands.run(command, timeout=timeout)
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.exit_code,
        }

    async def run_python(self, code: str, *, timeout: int = 30) -> dict:
        """Write the code to a temp file and run ``python`` on it.

        Returns ``{"stdout", "stderr", "exit_code"}``. Each call is a fresh
        interpreter — state persists via the filesystem, not in-memory.
        """
        tmp = f"/tmp/_swarm_run_{uuid.uuid4().hex}.py"
        await self._sandbox.files.write(tmp, code)
        try:
            return await self.execute(f"python {tmp}", timeout=timeout)
        finally:
            try:
                await self._sandbox.commands.run(f"rm -f {tmp}", timeout=5)
            except Exception:
                pass

    # ─── Conveniences used by the swarm conductor ───────────────────────────

    async def upload_text(self, path: str, content: str) -> None:
        """Write a text file ensuring parent dirs exist."""
        resolved = self._resolve(path)
        parent = os.path.dirname(resolved)
        if parent:
            try:
                await self._sandbox.files.make_dir(parent)
            except Exception:
                pass
        await self._sandbox.files.write(resolved, content)

    async def upload_bytes(self, path: str, content: bytes) -> None:
        """Write a binary file ensuring parent dirs exist."""
        resolved = self._resolve(path)
        parent = os.path.dirname(resolved)
        if parent:
            try:
                await self._sandbox.files.make_dir(parent)
            except Exception:
                pass
        await self._sandbox.files.write(resolved, content)

    async def list_files(self, path: str = "") -> list[dict]:
        """Alias for :meth:`ls` — kept separate so the artifact harvester has
        a stable name to grep for."""
        try:
            return await self.ls(path)
        except Exception:
            return []
