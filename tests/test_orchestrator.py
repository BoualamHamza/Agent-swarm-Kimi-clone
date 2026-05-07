"""Tests for the orchestrator — JSON validation and retry path."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.orchestrator import orchestrate

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def _completion(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.asyncio
@respx.mock
async def test_orchestrate_returns_validated_agents():
    valid = json.dumps({
        "reasoning": "Three independent dimensions.",
        "agents": [
            {"id": "a1", "name": "MarketAnalyst",  "role": "market sizing",       "task": "TAM/SAM/SOM"},
            {"id": "a2", "name": "TechArchitect",  "role": "tech feasibility",    "task": "stack + infra"},
            {"id": "a3", "name": "RiskAssessor",   "role": "risk identification", "task": "top 5 risks"},
        ],
    })
    respx.post(OPENROUTER).mock(return_value=httpx.Response(200, json=_completion(valid)))

    out = await orchestrate("Build a B2B SaaS")
    assert len(out.agents) == 3
    assert [a.id for a in out.agents] == ["a1", "a2", "a3"]
    assert out.agents[0].name == "MarketAnalyst"


@pytest.mark.asyncio
@respx.mock
async def test_orchestrate_retries_on_invalid_json():
    invalid = "not json at all"
    valid = json.dumps({
        "reasoning": "ok",
        "agents": [{"id": "a1", "name": "Foo", "role": "r", "task": "t"}],
    })

    route = respx.post(OPENROUTER)
    route.side_effect = [
        httpx.Response(200, json=_completion(invalid)),
        httpx.Response(200, json=_completion(valid)),
    ]

    out = await orchestrate("X")
    assert out.agents[0].name == "Foo"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_orchestrate_raises_on_persistent_invalid():
    respx.post(OPENROUTER).mock(return_value=httpx.Response(200, json=_completion("garbage")))

    with pytest.raises(RuntimeError, match="Orchestrator failed"):
        await orchestrate("X")
