"""Packaging invariants for the release wheel (issue #86).

The wheel build itself (and installing it into a clean venv) is exercised by
CI's `wheel-smoke` job; these pin the pieces that are testable in-process.
"""

from __future__ import annotations

import shutil
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

import deckifyr
from deckifyr import cli
from deckifyr.schema.errors import DeckifyrError

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_package_version_comes_from_the_version_file():
    try:
        installed = version("deckifyr")
    except PackageNotFoundError:
        pytest.skip("deckifyr is not installed (no distribution metadata)")
    expected = (REPO_ROOT / "VERSION").read_text().splitlines()[0].strip()
    # pyproject.toml reads VERSION (dynamic version), so the wheel, the
    # runtime `__version__` and a build manifest's `deckifyr_version` can
    # never drift from the release tag.
    assert installed == expected
    assert deckifyr.__version__ == expected


def test_version_is_not_hardcoded_in_pyproject():
    tomllib = pytest.importorskip("tomllib")  # stdlib from Python 3.11
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    # A static `version` in [project] would shadow VERSION and let the wheel
    # drift from the release tag.
    assert "version" not in config["project"]
    assert config["project"]["dynamic"] == ["version"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {"file": ["VERSION"]}


def test_examples_dir_finds_the_repo_example():
    found = cli._examples_dir()
    assert {p.name for p in found.glob("*.yaml")} >= {
        "design.yaml",
        "layouts.yaml",
        "presentation.yaml",
    }


def test_examples_dir_prefers_the_copy_bundled_into_a_wheel(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "deckifyr"
    bundled = package / "_examples" / "minimal-deck"
    bundled.mkdir(parents=True)
    (bundled / "design.yaml").write_text("x: 1\n")
    monkeypatch.setattr(cli, "__file__", str(package / "cli.py"))

    assert cli._examples_dir() == bundled.resolve()


def test_examples_dir_fails_clearly_when_the_example_is_nowhere(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "deckifyr"
    package.mkdir(parents=True)
    monkeypatch.setattr(cli, "__file__", str(package / "cli.py"))

    with pytest.raises(DeckifyrError, match="--from-dir"):
        cli._examples_dir()


def test_init_scaffolds_from_a_wheel_style_layout(tmp_path, monkeypatch, minimal_deck_dir):
    """`deckifyr init` with no flags works when the example lives in `_examples/`."""
    package = tmp_path / "site-packages" / "deckifyr"
    bundled = package / "_examples" / "minimal-deck"
    bundled.mkdir(parents=True)
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, bundled / name)
    monkeypatch.setattr(cli, "__file__", str(package / "cli.py"))

    target = tmp_path / "proj"
    assert cli.main(["init", str(target)]) == 0
    assert (target / "presentation.yaml").is_file()
