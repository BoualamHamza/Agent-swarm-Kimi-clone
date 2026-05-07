"""The agentic loop — OpenAI tool-calling protocol.

Pattern:
  1. Send messages → assistant either returns text (done) or tool_calls (continue).
  2. For each tool_call, parse JSON arguments, execute, append a {role:"tool", ...} message.
  3. Loop until done or max_iterations reached.

Handoff capture happens BEFORE the executor runs — same pattern as the JSX example.
That way the handoff `arguments` are preserved even if the executor logic changes.

Returns a `LoopOutcome` with a `status` field so callers can distinguish a
successful answer from soft-failure modes (max iterations, length truncation,
empty content). Reasoning models in particular can hit `length_truncated` when
they exhaust the token budget *during reasoning* and never produce content.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from app.client import get_openrouter
from app.state import (
    Handoff,
    HandoffRequested,
    LoopOutcome,
    MemoryWrite,
    SwarmEvent,
    ToolCallEvent,
    ToolCallRecord,
    ToolResultEvent,
)
from app.tools import ToolExecutor

logger = logging.getLogger(__name__)

EventEmitter = Callable[[SwarmEvent], Awaitable[None]]


async def tool_use_loop(
    *,
    agent_id: str,
    model: str,
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None = None,
    max_iterations: int = 15,
    max_tokens: int = 16000,  # reasoning-model headroom; non-reasoning models stop early
) -> LoopOutcome:
    """Run a single agent's tool-use loop and return a structured outcome."""
    client = get_openrouter()
    executor = ToolExecutor(shared_memory, lock)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    handoff: Handoff | None = None
    records: list[ToolCallRecord] = []

    for iteration in range(max_iterations):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,        # type: ignore[arg-type]
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason
        content = (msg.content or "").strip()

        # Done — no more tool calls
        if finish != "tool_calls" or not msg.tool_calls:
            if content:
                return LoopOutcome(text=content, status="ok", handoff=handoff, tool_calls=records)

            # Empty content — figure out which failure mode
            if finish == "length":
                # Reasoning model exhausted max_tokens during its reasoning chain
                # and never emitted content. Surface loudly.
                usage = getattr(resp, "usage", None)
                logger.warning(
                    "loop[%s] length-truncated empty content at iter %d (max_tokens=%d, usage=%s)",
                    agent_id, iteration, max_tokens, usage,
                )
                return LoopOutcome(
                    text="(model truncated by max_tokens before producing content)",
                    status="length_truncated", handoff=handoff, tool_calls=records,
                )

            logger.warning(
                "loop[%s] empty content at iter %d (finish_reason=%s)",
                agent_id, iteration, finish,
            )
            return LoopOutcome(
                text="(model returned no content)",
                status="empty", handoff=handoff, tool_calls=records,
            )

        # Append the assistant message with its tool_calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool, append a tool result message
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args: dict[str, Any] = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # Capture handoff intent BEFORE executor runs
            if name == "request_handoff" and handoff is None:
                try:
                    handoff = Handoff(**args)
                    if on_event:
                        await on_event(HandoffRequested(agent_id=agent_id, handoff=handoff))
                except Exception:
                    pass  # malformed handoff args — fall through to executor

            if on_event:
                await on_event(ToolCallEvent(agent_id=agent_id, name=name, input=args))

            result = await executor.execute(name, args)
            records.append(ToolCallRecord(name=name, input=args, result=result))

            if on_event:
                await on_event(ToolResultEvent(agent_id=agent_id, name=name, result=result))
                if name == "write_to_shared_memory" and "key" in args:
                    await on_event(MemoryWrite(
                        agent_id=agent_id,
                        key=str(args.get("key", "")),
                        value=str(args.get("value", "")),
                    ))

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    logger.warning("loop[%s] hit max_iterations=%d", agent_id, max_iterations)
    return LoopOutcome(
        text=f"(max iterations reached: {max_iterations})",
        status="max_iterations", handoff=handoff, tool_calls=records,
    )
