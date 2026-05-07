"""Per-role model defaults — cheap-and-fast preset.

Override per call via the `model=` argument on orchestrate / run_worker / aggregate,
or edit this dict directly.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    "orchestrator": "z-ai/glm-4.5-air:free",
    "worker":       "meta-llama/llama-3.3-70b-instruct:free",
    "aggregator":   "z-ai/glm-4.5-air:free",
}
