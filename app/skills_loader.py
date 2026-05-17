"""Discover and load procedural skills shipped inside the package.

Skills live at ``app/skills/{name}/SKILL.md`` and are markdown documents with
a small YAML frontmatter (``name``, ``description``) followed by the body.
At swarm startup the conductor uploads them into the sandbox so agents can
``read_file("/home/user/skills/{name}/SKILL.md")`` and follow the playbook.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # avoid circular import at module load
    from app.sandbox import SwarmSandbox


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL,
)
_FIELD_RE = re.compile(r"^(?P<key>[a-zA-Z_][\w-]*)\s*:\s*(?P<val>.*)$")


@dataclass(frozen=True)
class Skill:
    name: str          # from frontmatter ``name``
    description: str   # from frontmatter ``description``
    body: str          # markdown body (frontmatter stripped)
    relpath: str       # e.g. "python-runner/SKILL.md"


def _parse_skill(raw: str, relpath: str) -> Skill | None:
    """Parse a SKILL.md. Returns None if frontmatter is missing/invalid."""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group("fm").splitlines():
        fm = _FIELD_RE.match(line.strip())
        if fm:
            fields[fm.group("key")] = fm.group("val").strip()
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if not name:
        return None
    return Skill(
        name=name,
        description=description,
        body=m.group("body"),
        relpath=relpath,
    )


@lru_cache(maxsize=1)
def load_skills() -> tuple[Skill, ...]:
    """Walk ``app.skills`` and return every parseable SKILL.md as a Skill.

    Cached at module scope — skills don't change at runtime.
    Returns a tuple (hashable) so it plays nicely with ``lru_cache``.
    """
    skills: list[Skill] = []
    try:
        root = resources.files("app.skills")
    except (ModuleNotFoundError, FileNotFoundError):
        return tuple()

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parsed = _parse_skill(raw, f"{entry.name}/SKILL.md")
        if parsed is not None:
            skills.append(parsed)
    return tuple(skills)


def skills_prompt_section(skills: tuple[Skill, ...] | None = None) -> str:
    """Render the 'Available skills' bullet list for the worker system prompt.

    Returns the empty string when no skills are installed so the prompt
    stays clean.
    """
    skills = skills if skills is not None else load_skills()
    if not skills:
        return ""
    lines = [
        "",
        "Available skills (procedural playbooks loaded into the sandbox at /home/user/skills/):",
    ]
    for s in skills:
        lines.append(f"- {s.name} — {s.description}")
    lines.append("")
    lines.append(
        'To use a skill, read its full instructions via '
        'read_file("/home/user/skills/{name}/SKILL.md"), then follow the patterns it describes.'
    )
    return "\n".join(lines)


def skills_orchestrator_section(skills: tuple[Skill, ...] | None = None) -> str:
    """Render a condensed skills catalogue for the orchestrator system prompt.

    The orchestrator never invokes tools; it only needs to know which skills
    exist so it can mention them by name in each spawned agent's task.
    Returns an empty string when no skills are installed.
    """
    skills = skills if skills is not None else load_skills()
    if not skills:
        return ""
    lines = [
        "",
        "Available worker skills (procedural playbooks the workers can read at runtime):",
    ]
    for s in skills:
        lines.append(f"- {s.name} — {s.description}")
    lines.append("")
    lines.append(
        "When a spawned agent's task plainly matches one of the skills above, "
        "mention that skill by name in the agent's `task` field — e.g. "
        '"Use the `financial-analyst` skill to ...". Do NOT force a skill onto '
        "a task it does not fit; if no skill clearly applies, omit the mention."
    )
    return "\n".join(lines)


async def upload_skills(
    sandbox: "SwarmSandbox",
    skills: tuple[Skill, ...] | None = None,
) -> list[str]:
    """Upload each skill's SKILL.md to /home/user/skills/{name}/SKILL.md.

    Returns the list of absolute paths written. Failures are logged but do
    not raise — skills are best-effort enrichment, not a hard dependency.
    """
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    skills = skills if skills is not None else load_skills()
    if not skills:
        return []

    async def _one(skill: Skill) -> str | None:
        target = f"skills/{skill.name}/SKILL.md"
        try:
            return await sandbox.upload_text(target, _reassemble(skill)) or target
        except Exception as e:
            logger.warning("skill upload failed for %s: %s", skill.name, e)
            return None

    results = await asyncio.gather(*(_one(s) for s in skills))
    return [r for r in results if r]


def _reassemble(skill: Skill) -> str:
    """Reconstruct the full SKILL.md text from its parsed parts."""
    return (
        "---\n"
        f"name: {skill.name}\n"
        f"description: {skill.description}\n"
        "---\n\n"
        f"{skill.body}"
    )
