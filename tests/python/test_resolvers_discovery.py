import json

from deckifyr.resolvers.discovery import list_quarto_fragments, list_reportifyr_artifacts


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
