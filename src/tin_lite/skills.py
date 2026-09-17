from __future__ import annotations

from pathlib import Path

MAX_SKILL_SUITE_BYTES = 64_000


def load_skill_suite(path: Path) -> str:
    """Load an ordered filesystem-native skill suite for an execution agent."""
    skill_files = sorted(path.glob("[0-9][0-9]-*/SKILL.md"))
    if not skill_files:
        raise RuntimeError(f"skill suite {path} has no ordered SKILL.md files")
    sections = [skill_file.read_text() for skill_file in skill_files]
    content = "\n\n".join(sections)
    if len(content.encode()) > MAX_SKILL_SUITE_BYTES:
        raise RuntimeError(f"skill suite {path} exceeds {MAX_SKILL_SUITE_BYTES} bytes")
    return content
