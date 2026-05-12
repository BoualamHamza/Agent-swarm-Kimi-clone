"""Tests for the artifact harvest path in app.swarm + aggregator integration."""
from __future__ import annotations

from pathlib import Path

import pytest


# ─── Event model round-trip ──────────────────────────────────────────────────


def test_artifact_emitted_event_validates():
    from app.state import ArtifactEmitted

    ev = ArtifactEmitted(
        identifier="sess-1/chart.png",
        title="chart",
        mime_type="image/png",
        local_path="/tmp/chart.png",
        sandbox_path="/home/user/workspace/artifacts/chart.png",
        size_bytes=1234,
    )
    assert ev.type == "artifact_emitted"
    # Discriminated union must recognize it
    from app.state import SwarmEvent  # noqa: F401  -- presence is enough


# ─── Harvest ────────────────────────────────────────────────────────────────


class _StubSandbox:
    """Just enough surface for _list_artifact_names + _harvest_artifacts."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def list_files(self, path: str) -> list[dict]:
        if path != "/home/user/workspace/artifacts":
            return []
        return [
            {
                "name": name,
                "path": f"{path}/{name}",
                "is_dir": False,
                "size": len(data),
                "modified_at": "",
            }
            for name, data in self._files.items()
        ]

    async def read_bytes(self, path: str) -> bytes:
        name = path.rsplit("/", 1)[-1]
        return self._files[name]


@pytest.mark.asyncio
async def test_harvest_emits_one_event_per_file(tmp_path):
    from app.swarm import _harvest_artifacts, _list_artifact_names

    sb = _StubSandbox({
        "chart.png": b"\x89PNG\r\n\x1a\nbinary-bytes",
        "report.csv": b"a,b,c\n1,2,3\n",
    })

    names = await _list_artifact_names(sb)  # type: ignore[arg-type]
    assert set(names) == {"chart.png", "report.csv"}

    local_dir = tmp_path / "artifacts"
    local_dir.mkdir()
    events = [
        ev async for ev in _harvest_artifacts(
            sb, names, session_id="sess-1", local_dir=local_dir,  # type: ignore[arg-type]
        )
    ]
    assert len(events) == 2

    by_name = {ev.title: ev for ev in events}
    chart = by_name["chart"]
    assert chart.mime_type == "image/png"
    assert chart.sandbox_path == "/home/user/workspace/artifacts/chart.png"
    assert chart.identifier == "sess-1/chart.png"
    assert chart.size_bytes == len(sb._files["chart.png"])
    assert Path(chart.local_path).read_bytes() == sb._files["chart.png"]

    report = by_name["report"]
    assert report.mime_type == "text/csv"
    assert Path(report.local_path).is_file()


@pytest.mark.asyncio
async def test_harvest_handles_no_sandbox():
    from app.swarm import _list_artifact_names

    names = await _list_artifact_names(None)
    assert names == []


@pytest.mark.asyncio
async def test_harvest_handles_missing_dir():
    """If list_files raises (e.g. dir doesn't exist), return empty list."""
    from app.swarm import _list_artifact_names

    class Broken:
        async def list_files(self, path: str) -> list[dict]:
            raise RuntimeError("nope")

    names = await _list_artifact_names(Broken())  # type: ignore[arg-type]
    assert names == []


# ─── MIME guessing ──────────────────────────────────────────────────────────


def test_mime_guess_known_extensions():
    from app.swarm import _guess_mime

    assert _guess_mime("a.csv", b"a,b,c") == "text/csv"
    # png magic bytes
    assert _guess_mime("noext", b"\x89PNG\r\n\x1a\n...") == "image/png"
    # pdf magic bytes
    assert _guess_mime("noext", b"%PDF-1.4\n") == "application/pdf"


def test_mime_fallback_for_unknown():
    from app.swarm import _guess_mime

    assert _guess_mime("blob.dat", b"\x00\x01\x02") == "application/octet-stream"


# ─── Aggregator integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregator_mentions_artifacts_in_prompt(monkeypatch):
    """When ``artifacts`` is non-empty, the aggregator's user prompt must
    name them so the final answer can reference them."""
    from app.aggregator import aggregate

    captured: dict = {}

    class FakeChat:
        async def create(self, **kwargs):
            captured["messages"] = kwargs.get("messages", [])
            class _C:
                choices = [type("M", (), {"message": type("X", (), {"content": "done"})})]
            return _C()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeChat()})()

    monkeypatch.setattr("app.aggregator.get_openrouter", lambda: FakeClient())

    await aggregate(
        task="x",
        results=[],
        shared_memory={},
        artifacts=["chart.png", "summary.md"],
    )

    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    assert "chart.png" in user_msg["content"]
    assert "summary.md" in user_msg["content"]
    assert "/home/user/workspace/artifacts/" in user_msg["content"]


@pytest.mark.asyncio
async def test_aggregator_omits_artifact_note_when_empty(monkeypatch):
    from app.aggregator import aggregate

    captured: dict = {}

    class FakeChat:
        async def create(self, **kwargs):
            captured["messages"] = kwargs.get("messages", [])
            class _C:
                choices = [type("M", (), {"message": type("X", (), {"content": "done"})})]
            return _C()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeChat()})()

    monkeypatch.setattr("app.aggregator.get_openrouter", lambda: FakeClient())

    await aggregate(task="x", results=[], shared_memory={}, artifacts=None)
    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    assert "Deliverable files" not in user_msg["content"]
