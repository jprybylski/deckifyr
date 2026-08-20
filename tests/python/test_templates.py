import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from deckifyr.schema.errors import DeckifyrError, MissingDependencyError
from deckifyr.templates import (
    detect_template,
    fetch_git_template,
    materialize_template,
    resolve_repo_spec,
)

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not found on PATH"
)


# --- resolve_repo_spec ------------------------------------------------


def test_resolve_repo_spec_shorthand_defaults_to_github():
    source = resolve_repo_spec("acme/repo")
    assert source.clone_url == "https://github.com/acme/repo.git"
    assert source.ref is None
    assert source.subdir is None


def test_resolve_repo_spec_explicit_host_is_enterprise_support():
    source = resolve_repo_spec("git.example.com/acme/repo@v1")
    assert source.clone_url == "https://git.example.com/acme/repo.git"
    assert source.ref == "v1"


def test_resolve_repo_spec_embedded_subdir_and_ref():
    source = resolve_repo_spec("acme/repo/templates/foo@deadbeef")
    assert source.clone_url == "https://github.com/acme/repo.git"
    assert source.subdir == "templates/foo"
    assert source.ref == "deadbeef"


def test_resolve_repo_spec_full_url_passthrough():
    source = resolve_repo_spec(
        "https://example.com/acme/repo.git", ref="v3", subdir="templates/foo"
    )
    assert source.clone_url == "https://example.com/acme/repo.git"
    assert source.ref == "v3"
    assert source.subdir == "templates/foo"


def test_resolve_repo_spec_explicit_flags_override_embedded():
    source = resolve_repo_spec(
        "acme/repo/embedded-sub@embedded-ref", ref="explicit-ref", subdir="explicit-sub"
    )
    assert source.ref == "explicit-ref"
    assert source.subdir == "explicit-sub"


def test_resolve_repo_spec_owner_only_is_error():
    with pytest.raises(DeckifyrError):
        resolve_repo_spec("just-an-owner")


# --- detect_template ----------------------------------------------------


def _write_flat_source(root: Path, *, design_name="styleguide.yaml", layouts_name="zones.yaml"):
    root.mkdir(parents=True, exist_ok=True)
    (root / design_name).write_text(yaml.safe_dump({"deckifyr": "0.1", "colors": {}}))
    (root / layouts_name).write_text(yaml.safe_dump({"deckifyr": "0.1", "layouts": {}}))
    (root / "presentation.yaml").write_text(
        yaml.safe_dump(
            {
                "deckifyr": "0.1",
                "design": {"base": design_name},
                "layouts": layouts_name,
                "metadata": {"title": "Source Deck"},
                "build": {"output": "build/source.pptx"},
                "slides": [{"id": "s1", "layout": None, "elements": []}],
            }
        )
    )
    return root


def test_detect_template_flat_reads_original_filenames(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    resolved = detect_template(source, type_name=None)
    assert resolved.kind == "flat"
    assert resolved.design_filename == "styleguide.yaml"
    assert resolved.layouts_filename == "zones.yaml"


def test_detect_template_typed_without_type_lists_available_names(tmp_path):
    source = tmp_path / "source"
    _write_flat_source(source / "templates" / "alpha")
    _write_flat_source(source / "templates" / "beta")

    with pytest.raises(DeckifyrError) as exc_info:
        detect_template(source, type_name=None)
    assert "alpha" in str(exc_info.value)
    assert "beta" in str(exc_info.value)


def test_detect_template_typed_unknown_type_lists_available_names(tmp_path):
    source = tmp_path / "source"
    _write_flat_source(source / "templates" / "alpha")

    with pytest.raises(DeckifyrError) as exc_info:
        detect_template(source, type_name="bogus")
    assert "alpha" in str(exc_info.value)


def test_detect_template_typed_with_known_type(tmp_path):
    source = tmp_path / "source"
    _write_flat_source(source / "templates" / "alpha")
    resolved = detect_template(source, type_name="alpha")
    assert resolved.kind == "typed"


def test_detect_template_type_given_but_source_is_flat_is_an_error(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    with pytest.raises(DeckifyrError):
        detect_template(source, type_name="alpha")


def test_detect_template_neither_structure_is_an_error(tmp_path):
    source = tmp_path / "empty"
    source.mkdir()
    with pytest.raises(DeckifyrError):
        detect_template(source, type_name=None)


# --- materialize_template -------------------------------------------------


def test_materialize_flat_generates_a_schema_valid_minimal_presentation(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    resolved = detect_template(source, type_name=None)
    target = tmp_path / "my-new-deck"

    created, warnings = materialize_template(resolved, target, force=False)

    assert (target / "styleguide.yaml").is_file()
    assert (target / "zones.yaml").is_file()
    data = yaml.safe_load((target / "presentation.yaml").read_text())
    assert data["deckifyr"] == "0.1"
    assert data["design"] == {"base": "styleguide.yaml"}
    assert data["layouts"] == "zones.yaml"
    assert data["slides"] == []
    assert data["build"]["output"] == "build/my-new-deck.pptx"
    assert data["build"]["manifest"] == "build/my-new-deck.manifest.json"
    assert warnings == []
    assert len(created) == 3


def test_materialize_typed_copies_presentation_verbatim(tmp_path):
    source = tmp_path / "source"
    _write_flat_source(source / "templates" / "alpha")
    resolved = detect_template(source, type_name="alpha")
    target = tmp_path / "my-new-deck"

    created, _warnings = materialize_template(resolved, target, force=False)

    data = yaml.safe_load((target / "presentation.yaml").read_text())
    assert data["slides"] == [{"id": "s1", "layout": None, "elements": []}]
    assert len(created) == 3


def test_materialize_warns_about_uncopied_local_background_image(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    (source / "styleguide.yaml").write_text(
        yaml.safe_dump({"deckifyr": "0.1", "slide": {"background_image": "bg.png"}})
    )
    resolved = detect_template(source, type_name=None)
    _created, warnings = materialize_template(resolved, tmp_path / "target", force=False)
    assert any("bg.png" in w for w in warnings)


def test_materialize_does_not_warn_about_a_url_background_image(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    (source / "styleguide.yaml").write_text(
        yaml.safe_dump(
            {"deckifyr": "0.1", "slide": {"background_image": "https://example.com/bg.png"}}
        )
    )
    resolved = detect_template(source, type_name=None)
    _created, warnings = materialize_template(resolved, tmp_path / "target", force=False)
    assert warnings == []


def test_materialize_refuses_conflicting_file_without_force(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    resolved = detect_template(source, type_name=None)
    target = tmp_path / "target"
    target.mkdir()
    (target / "styleguide.yaml").write_text("sentinel")

    with pytest.raises(DeckifyrError):
        materialize_template(resolved, target, force=False)
    assert (target / "styleguide.yaml").read_text() == "sentinel"


def test_materialize_force_overwrites_conflicting_file(tmp_path):
    source = _write_flat_source(tmp_path / "source")
    resolved = detect_template(source, type_name=None)
    target = tmp_path / "target"
    target.mkdir()
    (target / "styleguide.yaml").write_text("sentinel")

    materialize_template(resolved, target, force=True)
    assert (target / "styleguide.yaml").read_text() != "sentinel"


# --- fetch_git_template (real git) ----------------------------------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _make_upstream_repo(root: Path) -> Path:
    repo = root / "upstream"
    repo.mkdir()
    _git("init", cwd=repo)
    _write_flat_source(repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    _git("tag", "v1", cwd=repo)
    return repo


@requires_git
def test_fetch_git_template_clones_and_checks_out_a_tag(tmp_path):
    repo = _make_upstream_repo(tmp_path)
    with fetch_git_template(str(repo), ref="v1", subdir=None) as source_dir:
        assert (source_dir / "presentation.yaml").is_file()


@requires_git
def test_fetch_git_template_scopes_into_a_subdir(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git("init", cwd=repo)
    _write_flat_source(repo / "templates" / "alpha")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)

    with fetch_git_template(str(repo), ref=None, subdir="templates/alpha") as source_dir:
        assert (source_dir / "presentation.yaml").is_file()


@requires_git
def test_fetch_git_template_missing_subdir_is_an_error(tmp_path):
    repo = _make_upstream_repo(tmp_path)
    with pytest.raises(DeckifyrError):
        with fetch_git_template(str(repo), ref="v1", subdir="does-not-exist"):
            pass


@requires_git
def test_fetch_git_template_bad_clone_url_is_an_error(tmp_path):
    with pytest.raises(DeckifyrError):
        with fetch_git_template(str(tmp_path / "does-not-exist"), ref=None, subdir=None):
            pass


def test_fetch_git_template_requires_git_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(MissingDependencyError):
        with fetch_git_template(str(tmp_path), ref=None, subdir=None):
            pass
