"""Keeps inst/python/deckifyr/skills/*/SKILL.md (the bundled coding-agent
skill content `deckifyr skills`/`deck_export_skills()` exports, issue
#50) structurally evergreen: since the content itself is hand-authored
prose (unlike inst/python/deckifyr/schemas/*.schema.json, which is
mechanically derived from a pydantic model -- see
test_json_schema_files.py), what's mechanically checkable here is the
Skills format contract each file must satisfy, not the prose itself.
"""

from pathlib import Path

import yaml

from deckifyr.cli import _SKILL_NAMES

SKILLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "python"
    / "deckifyr"
    / "skills"
)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "SKILL.md must start with a YAML frontmatter block"
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_every_skill_name_has_a_checked_in_directory():
    on_disk = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}
    assert on_disk == set(_SKILL_NAMES)


def test_every_skill_has_a_skill_md_file():
    for name in _SKILL_NAMES:
        assert (SKILLS_DIR / name / "SKILL.md").is_file()


def test_frontmatter_name_matches_the_containing_directory():
    for name in _SKILL_NAMES:
        text = (SKILLS_DIR / name / "SKILL.md").read_text()
        frontmatter, _ = _split_frontmatter(text)
        assert frontmatter["name"] == name


def test_frontmatter_description_is_a_non_empty_string():
    for name in _SKILL_NAMES:
        text = (SKILLS_DIR / name / "SKILL.md").read_text()
        frontmatter, _ = _split_frontmatter(text)
        assert isinstance(frontmatter["description"], str)
        assert frontmatter["description"].strip()


def test_body_is_non_empty():
    for name in _SKILL_NAMES:
        text = (SKILLS_DIR / name / "SKILL.md").read_text()
        _, body = _split_frontmatter(text)
        assert body.strip()
