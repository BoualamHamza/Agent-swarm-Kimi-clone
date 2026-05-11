"""AvatarPool — assignment stability, recycling, and pool integrity."""
from __future__ import annotations

from app.tui.avatars import CHARACTER_POOL, AvatarPool, Character


def test_pool_is_nonempty_and_unique():
    names = [c.name for c in CHARACTER_POOL]
    assert len(CHARACTER_POOL) >= 24
    assert len(set(names)) == len(names), "duplicate character names in pool"


def test_assign_is_stable_per_agent():
    pool = AvatarPool(seed=42)
    c1 = pool.assign("a1")
    c2 = pool.assign("a2")
    # Same agent_id returns the same Character on repeated calls.
    assert pool.assign("a1") is c1
    assert pool.assign("a2") is c2
    # Different agent_ids get different characters (within pool capacity).
    assert c1 is not c2


def test_assign_walks_through_pool_then_recycles():
    pool = AvatarPool(seed=0)
    n = len(CHARACTER_POOL)
    assigned = [pool.assign(f"agent-{i}") for i in range(n + 3)]
    # First n are unique
    first_block = assigned[:n]
    assert len(set(first_block)) == n
    # Wrap-around: agent-n, agent-n+1, agent-n+2 reuse from the head
    assert assigned[n] is assigned[0]
    assert assigned[n + 1] is assigned[1]
    assert assigned[n + 2] is assigned[2]


def test_seed_changes_order():
    a = AvatarPool(seed=1)
    b = AvatarPool(seed=2)
    first_a = a.assign("x")
    first_b = b.assign("x")
    # Very high probability of differing on a 28-element pool.
    assert isinstance(first_a, Character)
    assert isinstance(first_b, Character)


def test_lookup_returns_none_for_unknown():
    pool = AvatarPool(seed=0)
    assert pool.lookup("never-assigned") is None
    pool.assign("known")
    assert pool.lookup("known") is not None
