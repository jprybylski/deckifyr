import json

import pytest

from deckifyr.resolvers.discovery import (
    list_project_directory,
    list_quarto_fragments,
    list_reportifyr_artifacts,
)
from deckifyr.schema.errors import ContentValidationError


def _write_artifact(tmp_path, *, name="conc-time.png", with_metadata=True, outputs_dir="OUTPUTS"):
    outdir = tmp_path / outputs_dir
    outdir.mkdir(parents=True, exist_ok=True)
    artifact = outdir / name
    artifact.write_bytes(b"fake-bytes")
    if with_metadata:
        stem, ext = name.rsplit(".", 1)
        (outdir / f"{stem}_{ext}_metadata.json").write_text(json.dumps({}))
    return artifact


def test_list_reportifyr_artifacts_finds_artifacts_with_a_metadata_sidecar(tmp_path):
    _write_artifact(tmp_path, name="conc-time.png")
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == ["conc-time.png"]


def test_list_reportifyr_artifacts_excludes_artifacts_with_no_sidecar(tmp_path):
    _write_artifact(tmp_path, name="conc-time.png", with_metadata=False)
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == []


def test_list_reportifyr_artifacts_excludes_an_orphaned_sidecar_with_no_artifact(tmp_path):
    outdir = tmp_path / "OUTPUTS"
    outdir.mkdir()
    (outdir / "ghost_png_metadata.json").write_text("{}")
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == []


def test_list_reportifyr_artifacts_handles_underscores_in_the_stem(tmp_path):
    _write_artifact(tmp_path, name="conc_time_plot.png")
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == ["conc_time_plot.png"]


def test_list_reportifyr_artifacts_searches_recursively(tmp_path):
    _write_artifact(tmp_path, name="a.png", outputs_dir="OUTPUTS/figures")
    _write_artifact(tmp_path, name="b.csv", outputs_dir="OUTPUTS")
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == ["a.png", "b.csv"]


def test_list_reportifyr_artifacts_returns_empty_when_outputs_dir_missing(tmp_path):
    assert list_reportifyr_artifacts(tmp_path, "OUTPUTS") == []


def test_list_quarto_fragments_finds_qmd_files_recursively(tmp_path):
    (tmp_path / "a.qmd").write_text("# hi\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.qmd").write_text("# hi\n")
    (tmp_path / "not-a-fragment.md").write_text("hi\n")
    assert list_quarto_fragments(tmp_path) == ["a.qmd", "sub/b.qmd"]


def test_list_quarto_fragments_returns_empty_for_no_fragments(tmp_path):
    assert list_quarto_fragments(tmp_path) == []


def test_list_project_directory_lists_root_entries(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "sub").mkdir()
    dirs, files, truncated = list_project_directory(tmp_path, "")
    assert dirs == ["sub"]
    assert files == ["a.txt"]
    assert truncated is False


def test_list_project_directory_navigates_one_level_into_a_subdirectory(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("hi")
    (sub / "deeper").mkdir()
    dirs, files, truncated = list_project_directory(tmp_path, "sub")
    assert dirs == ["deeper"]
    assert files == ["nested.txt"]
    assert truncated is False


def test_list_project_directory_empty_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    assert list_project_directory(tmp_path, "empty") == ([], [], False)


def test_list_project_directory_rejects_a_dir_that_escapes_the_project_root(tmp_path):
    with pytest.raises(ContentValidationError):
        list_project_directory(tmp_path, "../../etc")


def test_list_project_directory_rejects_a_dir_that_is_not_a_directory(tmp_path):
    (tmp_path / "a-file.txt").write_text("hi")
    with pytest.raises(ContentValidationError):
        list_project_directory(tmp_path, "a-file.txt")


def test_list_project_directory_caps_a_huge_directory_and_flags_truncation(tmp_path):
    dense = tmp_path / "dense"
    dense.mkdir()
    # Well past `_MAX_BROWSE_ENTRIES` -- stands in for a populated
    # `renv/library/<hash>` cache dir or similar (issue #32's own
    # motivating concern), confirming this never returns an unbounded
    # response even for one single (non-recursive) directory level.
    for i in range(600):
        (dense / f"f{i:04d}.txt").write_text("")
    dirs, files, truncated = list_project_directory(tmp_path, "dense")
    assert dirs == []
    assert len(files) == 500
    assert truncated is True


def test_list_project_directory_never_recurses_below_the_requested_level(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    deeper = sub / "deeper"
    deeper.mkdir()
    # A huge tree *underneath* the requested directory must not be walked
    # at all -- only `sub`'s own immediate children matter.
    for i in range(2000):
        (deeper / f"f{i:04d}.txt").write_text("")
    dirs, files, truncated = list_project_directory(tmp_path, "sub")
    assert dirs == ["deeper"]
    assert files == []
    assert truncated is False
