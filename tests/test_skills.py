"""Tests for app.skills_loader — load, parse, prompt section, and upload."""
from __future__ import annotations

import pytest


EXPECTED_SKILLS = {
    "python-runner", "data-analyst", "file-manager",
    "web-scraper", "data-vulgariser", "financial-analyst",
    "xlsx", "pptx",
}


def test_load_skills_finds_all_bundled():
    from app.skills_loader import load_skills

    skills = load_skills()
    names = {s.name for s in skills}
    assert names == EXPECTED_SKILLS


def test_descriptions_are_non_empty():
    from app.skills_loader import load_skills

    skills = load_skills()
    for s in skills:
        assert s.description, f"{s.name} has no description"


def test_body_does_not_contain_frontmatter():
    """The parser must strip the leading `---...---` YAML block."""
    from app.skills_loader import load_skills

    for s in load_skills():
        assert not s.body.lstrip().startswith("---"), f"{s.name} kept frontmatter"
        # The body should still contain the H1 / markdown heading
        assert "##" in s.body or "#" in s.body, f"{s.name} body looks empty"


def test_skills_prompt_section_mentions_every_skill():
    from app.skills_loader import skills_prompt_section

    text = skills_prompt_section()
    for name in EXPECTED_SKILLS:
        assert name in text, f"prompt section missing {name}"
    assert "/home/user/skills/" in text


def test_skills_prompt_section_empty_when_no_skills():
    from app.skills_loader import skills_prompt_section

    text = skills_prompt_section(skills=tuple())
    assert text == ""


def test_worker_system_prompt_includes_skill_names():
    """The worker's system prompt builder must surface the skill list so the
    LLM knows what's available."""
    from app.state import AgentSpec
    from app.worker import _worker_system

    spec = AgentSpec(id="a1", name="TestAgent", role="tester", task="do something")
    prompt = _worker_system(spec, "outer task")
    assert "python-runner" in prompt
    assert "data-analyst" in prompt
    # The workspace section must also be present (mentioned in the same prompt).
    assert "/home/user/workspace/" in prompt


@pytest.mark.asyncio
async def test_upload_skills_writes_to_correct_paths():
    """upload_skills delegates to sandbox.upload_text / upload_bytes; verify
    each SKILL.md lands at skills/{name}/SKILL.md and bundled assets land
    at skills/{name}/{relpath} (e.g. skills/xlsx/scripts/recalc.py)."""
    from app.skills_loader import load_skills, upload_skills

    text_writes: list[tuple[str, str]] = []
    byte_writes: list[tuple[str, bytes]] = []

    class StubSandbox:
        async def upload_text(self, path: str, content: str) -> str:
            text_writes.append((path, content))
            return path

        async def upload_bytes(self, path: str, content: bytes) -> str:
            byte_writes.append((path, content))
            return path

    sb = StubSandbox()
    await upload_skills(sb)  # type: ignore[arg-type]

    written_paths = {p for p, _ in text_writes} | {p for p, _ in byte_writes}
    skills = load_skills()

    # SKILL.md for every skill must be uploaded
    skill_md_paths = {f"skills/{s.name}/SKILL.md" for s in skills}
    assert skill_md_paths.issubset(written_paths)

    # Each SKILL.md upload should reattach the frontmatter
    for path, content in text_writes:
        if not path.endswith("/SKILL.md"):
            continue
        assert content.startswith("---\n")
        assert "\n---\n" in content
        skill_name = path.split("/")[1]
        assert f"name: {skill_name}" in content

    # Every bundled asset must also be uploaded under its skill folder
    for s in skills:
        for asset in s.assets:
            expected = f"skills/{s.name}/{asset.relpath}"
            assert expected in written_paths, f"missing asset upload: {expected}"
