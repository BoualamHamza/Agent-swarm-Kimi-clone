"""Tests for app.skills_loader — load, parse, prompt section, and upload."""
from __future__ import annotations

import pytest


def test_load_skills_finds_all_bundled():
    from app.skills_loader import load_skills

    skills = load_skills()
    names = {s.name for s in skills}
    assert names == {
        "python-runner", "data-analyst", "file-manager",
        "web-scraper", "data-vulgariser", "financial-analyst",
    }


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
    for name in (
        "python-runner", "data-analyst", "file-manager",
        "web-scraper", "data-vulgariser", "financial-analyst",
    ):
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
    prompt = _worker_system(spec, "outer task", [spec])
    assert "python-runner" in prompt
    assert "data-analyst" in prompt
    # The workspace section must also be present (mentioned in the same prompt).
    assert "/home/user/workspace/" in prompt


@pytest.mark.asyncio
async def test_upload_skills_writes_to_correct_paths():
    """upload_skills delegates to sandbox.upload_text; verify each call lands
    at /home/user/skills/{name}/SKILL.md (or skills/{name}/SKILL.md before
    resolution)."""
    from app.skills_loader import load_skills, upload_skills

    writes: list[tuple[str, str]] = []

    class StubSandbox:
        async def upload_text(self, path: str, content: str) -> str:
            writes.append((path, content))
            return path

    sb = StubSandbox()
    await upload_skills(sb)  # type: ignore[arg-type]

    written_paths = {p for p, _ in writes}
    expected = {f"skills/{s.name}/SKILL.md" for s in load_skills()}
    assert written_paths == expected

    # Each upload should contain the full skill text (frontmatter reattached)
    for path, content in writes:
        assert content.startswith("---\n")
        assert "\n---\n" in content
        # path looks like "skills/<name>/SKILL.md"
        skill_name = path.split("/")[1]
        assert f"name: {skill_name}" in content
