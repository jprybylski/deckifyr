"""Project files written by Windows tools may start with a UTF-8 byte order
mark (Windows PowerShell 5.1 `Set-Content -Encoding utf8`, older Notepad).
Issue #94: they must load exactly like the same file without one."""

import json
import shutil
from pathlib import Path

import pytest

from deckifyr.cli import EXIT_OK, main
from deckifyr.resolvers import BuildContext, TableResolver
from deckifyr.resolvers.reportifyr import (
    ReportifyrResolver,
    load_standard_footnotes,
)
from deckifyr.resolvers.reportifyr import metadata_sidecar_path
from deckifyr.textio import read_project_text

BOM = b"\xef\xbb\xbf"
DOCS = ("design.yaml", "layouts.yaml", "presentation.yaml")


@pytest.fixture(autouse=True)
def windows_ansi_default_encoding(monkeypatch):
    """Windows' default text encoding is cp1252, not UTF-8, so a BOM read
    without an explicit encoding becomes literal characters (``ï»¿``) at the
    start of the first YAML key. PyYAML skips a leading U+FEFF itself, so on
    a UTF-8 machine (macOS/Linux) the bug is invisible; simulate the
    Windows default so these tests fail without the fix on any OS."""
    real_read_text = Path.read_text

    def read_text(self, encoding=None, errors=None, newline=None):
        return real_read_text(self, encoding or "cp1252", errors)

    monkeypatch.setattr(Path, "read_text", read_text)


def _add_bom(path: Path) -> None:
    data = path.read_bytes()
    assert not data.startswith(BOM)
    path.write_bytes(BOM + data)


def _copy_deck(minimal_deck_dir: Path, tmp_path: Path) -> None:
    for name in DOCS:
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)


@pytest.mark.parametrize("bom_doc", DOCS)
def test_validate_accepts_a_bom_on_each_document(minimal_deck_dir, tmp_path, capsys, bom_doc):
    _copy_deck(minimal_deck_dir, tmp_path)
    _add_bom(tmp_path / bom_doc)

    exit_code = main(["--json", "validate", str(tmp_path / "presentation.yaml")])

    assert exit_code == EXIT_OK, capsys.readouterr()
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_build_accepts_a_bom_on_every_document(minimal_deck_dir, tmp_path, capsys):
    _copy_deck(minimal_deck_dir, tmp_path)
    for name in DOCS:
        _add_bom(tmp_path / name)

    exit_code = main(["--json", "build", str(tmp_path / "presentation.yaml")])

    assert exit_code == EXIT_OK
    assert json.loads(capsys.readouterr().out)["slide_count"] == 2


def test_files_without_a_bom_are_unaffected(minimal_deck_dir, tmp_path, capsys):
    _copy_deck(minimal_deck_dir, tmp_path)

    exit_code = main(["--json", "validate", str(tmp_path / "presentation.yaml")])

    assert exit_code == EXIT_OK


def test_get_reads_a_bom_prefixed_file(minimal_deck_dir, tmp_path, capsys):
    # `get`/`set`/`slide` go through projectio.read_yaml, not load_project.
    _copy_deck(minimal_deck_dir, tmp_path)
    _add_bom(tmp_path / "design.yaml")

    exit_code = main(["--json", "get", str(tmp_path / "design.yaml"), "deckifyr"])

    assert exit_code == EXIT_OK


def test_set_writes_back_bom_free_utf8(minimal_deck_dir, tmp_path, capsys):
    _copy_deck(minimal_deck_dir, tmp_path)
    _add_bom(tmp_path / "presentation.yaml")

    exit_code = main(
        ["--json", "set", str(tmp_path / "presentation.yaml"), "metadata.title", "Café"]
    )

    assert exit_code == EXIT_OK
    written = (tmp_path / "presentation.yaml").read_bytes()
    assert not written.startswith(BOM)
    assert "Café".encode("utf-8") in written


def test_non_ascii_text_decodes_as_utf8(tmp_path):
    # Without an explicit encoding Windows decodes this as cp1252.
    path = tmp_path / "x.yaml"
    path.write_bytes(BOM + "title: Café – résumé\n".encode("utf-8"))

    assert read_project_text(path) == "title: Café – résumé\n"


def test_csv_table_header_has_no_bom(tmp_path):
    # Excel on Windows saves "CSV UTF-8" with a BOM; it must not end up
    # in the first column name.
    (tmp_path / "data.csv").write_bytes(BOM + b"name,score\nAda,10\n")

    resolved = TableResolver().resolve("data.csv", BuildContext(project_root=str(tmp_path)))

    assert resolved.value.headers[0] == "name"


def test_standard_footnotes_with_a_bom(tmp_path):
    path = tmp_path / "standard_footnotes.yaml"
    path.write_bytes(BOM + b"figure_footnotes:\n  a: A note\n")

    assert load_standard_footnotes(path) == {"figure_footnotes": {"a": "A note"}}


def test_reportifyr_metadata_sidecar_with_a_bom(tmp_path):
    outdir = tmp_path / "OUTPUTS"
    outdir.mkdir()
    artifact = outdir / "fig.png"
    artifact.write_bytes(b"png")
    metadata_sidecar_path(artifact).write_bytes(
        BOM + json.dumps({"object_meta": {"meta_type": "m"}}).encode("utf-8")
    )

    resolved = ReportifyrResolver().resolve(
        "{rpfy}:fig.png", BuildContext(project_root=str(tmp_path))
    )

    assert resolved.value.metadata == {"object_meta": {"meta_type": "m"}}
    assert not any("invalid JSON" in str(w) for w in resolved.value.warnings)
