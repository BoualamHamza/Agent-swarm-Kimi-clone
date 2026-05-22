"""The agentic loop — OpenAI tool-calling protocol.

Pattern:
  1. Send messages → assistant either returns text (done) or tool_calls (continue).
  2. For each tool_call, parse JSON arguments, execute, append a {role:"tool", ...} message.
  3. Loop until done or max_iterations reached.

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
from app.memory import SharedMemoryStore
from app.sandbox import SwarmSandbox
from app.state import (
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
    max_iterations: int = 25,
    max_tokens: int = 16000,  # reasoning-model headroom; non-reasoning models stop early
    store: SharedMemoryStore | None = None,
    session_id: str | None = None,
    sandbox: SwarmSandbox | None = None,
    persist_tool: str | None = None,
    max_persist_nudges: int = 2,
) -> LoopOutcome:
    """Run a single agent's tool-use loop and return a structured outcome.

    If ``persist_tool`` is set, the loop refuses to accept a clean exit until the
    agent has called that tool at least once. When the model tries to end without
    it, the loop injects a reminder and continues, up to ``max_persist_nudges``
    times. This stops agents that gather data in-context but never save it.
    """
    client = get_openrouter()
    executor = ToolExecutor(
        shared_memory, lock,
        store=store, session_id=session_id, sandbox=sandbox,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    records: list[ToolCallRecord] = []
    persist_nudges = 0

    try:
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
                # Persistence guard: don't accept an exit from an agent that
                # gathered data but never saved it. Nudge it to persist first.
                if (persist_tool
                        and persist_nudges < max_persist_nudges
                        and not any(r.name == persist_tool for r in records)):
                    persist_nudges += 1
                    logger.warning(
                        "loop[%s] exiting without %s — nudging (%d/%d)",
                        agent_id, persist_tool, persist_nudges, max_persist_nudges,
                    )
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "(no content)",
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You are ending your turn but have not called "
                            f"`{persist_tool}`. Any findings you gathered will be "
                            f"LOST unless you persist them now. Call `{persist_tool}` "
                            f"with your structured findings (include source URLs), "
                            f"then finish."
                        ),
                    })
                    continue

                if content:
                    return LoopOutcome(text=content, status="ok", tool_calls=records)

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
                        status="length_truncated", tool_calls=records,
                    )

                logger.warning(
                    "loop[%s] empty content at iter %d (finish_reason=%s)",
                    agent_id, iteration, finish,
                )
                return LoopOutcome(
                    text="(model returned no content)",
                    status="empty", tool_calls=records,
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
                    args: dict[str, Any] = json.loads(
                        tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                if on_event:
                    await on_event(ToolCallEvent(agent_id=agent_id, name=name, input=args))

                result = await executor.execute(name, args)
                records.append(ToolCallRecord(
                    name=name, input=args, result=result))

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

        logger.warning("loop[%s] hit max_iterations=%d",
                       agent_id, max_iterations)
        return LoopOutcome(
            text=f"(max iterations reached: {max_iterations})",
            status="max_iterations", tool_calls=records,
        )
    finally:
        await executor.close()
