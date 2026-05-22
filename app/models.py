"""Per-role model defaults — cheap-and-fast preset.

Override per call via the `model=` argument on orchestrate / run_worker / aggregate,
or edit this dict directly.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    "orchestrator": "deepseek/deepseek-v4-pro",
    "worker":       "deepseek/deepseek-v4-pro",
}
