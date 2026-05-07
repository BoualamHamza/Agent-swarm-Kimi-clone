## 1. What Is an Agent Swarm?

An **agent swarm** is a multi-agent system where multiple AI agents work in parallel on sub-tasks, communicate with each other through shared state, and can dynamically redirect work to newly spawned specialists mid-execution.

It is distinct from two simpler patterns:

| Pattern                   | Description                                                        | Limitation                                      |
| ------------------------- | ------------------------------------------------------------------ | ----------------------------------------------- |
| **Single Agent**          | One LLM handles everything sequentially                            | Slow; bottlenecked by context                   |
| **N Parallel Sub-agents** | N agents run the same task on N slices of data                     | Agents are blind to each other; no coordination |
| **Agent Swarm**           | Agents run in parallel, share findings, and route work dynamically | More complex, but genuinely collaborative       |

The key difference between N sub-agents and a swarm is **rich inter-agent communication that can change the execution graph mid-flight**. Agents are not isolated — they read each other's findings and can spawn new peers when they discover work outside their specialization.

### Inspiration: Kimi K2.5

This architecture is inspired by Moonshot AI's Kimi K2.5 agent swarm, which trains parallelism as a skill using **Parallel-Agent Reinforcement Learning (PARL)**. Key properties we replicate:

- The **model decides** how many agents to spawn (not the engineer)
- Sub-agents are **frozen workers** dispatched on demand
- An internal **scheduling mechanism** manages concurrency
- Agents share a **common information space**
- The system can **decide not to parallelize** when a task doesn't warrant it

---

## 2. Core Concepts

### Orchestrator

The **Orchestrator** is a single LLM call that receives the user's task and decides how to decompose it. It defines:

- How many worker agents to spawn (typically 3–5)
- Each agent's name, role, and specific sub-task
- The reasoning behind the decomposition

The Orchestrator does **not** have tools. It is purely a planning step. Its output is a JSON manifest of agents.

```json
{
  "reasoning": "This task requires parallel analysis of three independent dimensions.",
  "agents": [
    {
      "id": "a1",
      "name": "MarketAnalyst",
      "role": "market sizing and competitive landscape",
      "task": "Analyze the TAM, SAM, SOM and key competitors for a B2B SaaS product"
    },
    {
      "id": "a2",
      "name": "TechArchitect",
      "role": "technical feasibility and stack selection",
      "task": "Evaluate build vs buy, recommended stack, and infrastructure costs"
    },
    {
      "id": "a3",
      "name": "RiskAssessor",
      "role": "risk identification and mitigation",
      "task": "Identify top 5 risks and propose mitigations for a Series A fintech startup"
    }
  ]
}
```

### Worker Agent

A **Worker Agent** is an LLM call with tools. Each worker:

- Has a defined role and a specific task
- Is aware of the full swarm (knows other agents' names and roles)
- Starts by reading shared memory to see what others have found
- Writes its own findings to shared memory
- Can request a handoff if it discovers work outside its specialty

### Handoff Agent

A **Handoff Agent** is a new worker spawned **dynamically at runtime** because a worker flagged work requiring a different specialist. It:

- Receives the originating agent's partial result as context
- Reads the full shared memory to understand the swarm's state
- Runs with the same tool set as a regular worker

### Shared Memory

A **key-value store** visible to all agents simultaneously. Any agent can write findings; any agent can read all findings. This is the mechanism that transforms independent parallel workers into a coordinated swarm.

### Aggregator

A final LLM call (no tools) that receives all worker and handoff results plus the shared memory dump, and synthesizes them into a single coherent answer.

---
