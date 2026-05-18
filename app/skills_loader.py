"""Discover and load procedural skills shipped inside the package.

Each skill is a directory under ``app/skills/{name}/`` containing at minimum
a ``SKILL.md`` (markdown body + YAML frontmatter with ``name`` and
``description``). Skills may also ship auxiliary files — Python helpers under
``scripts/``, additional markdown references, templates, etc. — and the
loader uploads the **entire skill folder** into the sandbox at
``/home/user/skills/{name}/`` so workers can execute the bundled helpers
directly (e.g. ``python /home/user/skills/xlsx/scripts/recalc.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from importlib.resources.abc import Traversable
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # avoid circular import at module load
    from app.sandbox import SwarmSandbox


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL,
)
_FIELD_RE = re.compile(r"^(?P<key>[a-zA-Z_][\w-]*)\s*:\s*(?P<val>.*)$")

# Files we never ship into the sandbox even if they live inside a skill dir.
_SKIP_NAMES = {".DS_Store", "__pycache__", ".gitignore", ".gitkeep"}
# Suffixes treated as text (everything else is uploaded as bytes).
_TEXT_SUFFIXES = {
    ".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".js", ".ts", ".html", ".css", ".csv", ".tsv", ".sh",
}


@dataclass(frozen=True)
class SkillAsset:
    """A non-SKILL.md file shipped with a skill."""
    relpath: str   # path relative to the skill directory, e.g. "scripts/recalc.py"
    text: str | None = None    # populated for text assets
    data: bytes | None = None  # populated for binary assets


@dataclass(frozen=True)
class Skill:
    name: str          # from frontmatter ``name``
    description: str   # from frontmatter ``description``
    body: str          # markdown body (frontmatter stripped)
    relpath: str       # e.g. "python-runner/SKILL.md"
    assets: tuple[SkillAsset, ...] = field(default_factory=tuple)


def _parse_skill(raw: str, relpath: str, assets: tuple[SkillAsset, ...]) -> Skill | None:
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
        assets=assets,
    )


def _is_text(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(s) for s in _TEXT_SUFFIXES)


def _collect_assets(skill_root: Traversable) -> tuple[SkillAsset, ...]:
    """Walk a skill directory and return every file except SKILL.md."""
    assets: list[SkillAsset] = []

    def _walk(node: Traversable, rel_prefix: str) -> None:
        for child in sorted(node.iterdir(), key=lambda p: p.name):
            if child.name in _SKIP_NAMES:
                continue
            rel = f"{rel_prefix}{child.name}" if rel_prefix else child.name
            if child.is_dir():
                _walk(child, rel + "/")
                continue
            if rel == "SKILL.md":
                continue
            if _is_text(child.name):
                try:
                    text = child.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                assets.append(SkillAsset(relpath=rel, text=text))
            else:
                try:
                    data = child.read_bytes()
                except OSError:
                    continue
                assets.append(SkillAsset(relpath=rel, data=data))

    _walk(skill_root, "")
    return tuple(assets)


@lru_cache(maxsize=1)
def load_skills() -> tuple[Skill, ...]:
    """Walk ``app.skills`` and return every parseable skill with its bundled
    assets. Cached at module scope — skills don't change at runtime.
    """
    skills: list[Skill] = []
    try:
        root = resources.files("app.skills")
    except (ModuleNotFoundError, FileNotFoundError):
        return tuple()

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.name in _SKIP_NAMES:
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        assets = _collect_assets(entry)
        parsed = _parse_skill(raw, f"{entry.name}/SKILL.md", assets)
        if parsed is not None:
            skills.append(parsed)
    return tuple(skills)


def skills_prompt_section(skills: tuple[Skill, ...] | None = None) -> str:
    """Render the 'Available skills' bullet list for the worker system prompt."""
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
        'read_file("/home/user/skills/{name}/SKILL.md"), then follow the patterns it describes. '
        'Some skills bundle helper scripts under /home/user/skills/{name}/scripts/ — '
        'invoke them with execute() or run_python().'
    )
    return "\n".join(lines)


def skills_orchestrator_section(skills: tuple[Skill, ...] | None = None) -> str:
    """Render a condensed skills catalogue for the orchestrator system prompt."""
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
    """Upload each skill's SKILL.md plus every bundled asset to
    ``/home/user/skills/{name}/`` (preserving subdirectories).

    Returns the list of relative paths written. Failures are logged but do
    not raise — skills are best-effort enrichment, not a hard dependency.
    """
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    skills = skills if skills is not None else load_skills()
    if not skills:
        return []

    async def _upload_one_file(target: str, payload: str | bytes) -> str | None:
        try:
            if isinstance(payload, str):
                await sandbox.upload_text(target, payload)
            else:
                await sandbox.upload_bytes(target, payload)
            return target
        except Exception as e:
            logger.warning("skill upload failed for %s: %s", target, e)
            return None

    async def _one(skill: Skill) -> list[str]:
        jobs: list = [
            _upload_one_file(f"skills/{skill.name}/SKILL.md", _reassemble(skill)),
        ]
        for asset in skill.assets:
            target = f"skills/{skill.name}/{asset.relpath}"
            payload: str | bytes = asset.text if asset.text is not None else (asset.data or b"")
            jobs.append(_upload_one_file(target, payload))
        results = await asyncio.gather(*jobs)
        return [r for r in results if r]

    grouped = await asyncio.gather(*(_one(s) for s in skills))
    return [path for sub in grouped for path in sub]


def _reassemble(skill: Skill) -> str:
    """Reconstruct the full SKILL.md text from its parsed parts."""
    return (
        "---\n"
        f"name: {skill.name}\n"
        f"description: {skill.description}\n"
        "---\n\n"
        f"{skill.body}"
    )
