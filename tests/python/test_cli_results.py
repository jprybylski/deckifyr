"""Versioned `--json` results and structured warnings (issue #85).

Every payload here is *real CLI output* (via `main()`), validated against the
published result models -- so a handler that grows a key, drops one, or forgets
`result_version` fails here rather than in a consumer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image

from deckifyr.cli import EXIT_OK, main
from deckifyr.schema.results import (
    RESULT_VERSION,
    BuildResultPayload,
    ErrorResult,
    OkResult,
    PreviewResultPayload,
    ValidateResult,
)

requires_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="soffice binary not found on PATH"
)


def _copy_deck(minimal_deck_dir, tmp_path):
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path / "presentation.yaml"


def _warning_project(minimal_deck_dir, tmp_path, *, manifest: bool):
    """A deck with one known warning: a reportifyr figure with no metadata sidecar."""
    presentation_path = _copy_deck(minimal_deck_dir, tmp_path)
    (tmp_path / "OUTPUTS").mkdir()
    Image.new("RGB", (40, 20), color="blue").save(tmp_path / "OUTPUTS" / "fig.png")
    data = yaml.safe_load(presentation_path.read_text())
    data["build"]["reportifyr"] = {"fail_on_missing_metadata": False}
    if not manifest:
        del data["build"]["manifest"]
    data["slides"][0]["elements"].append(
        {
            "id": "fig",
            "type": "reportifyr",
            "value": "{rpfy}:fig.png",
            "alt_text": "a test figure",
            "box": {"x": "1in", "y": "4in", "width": "4in", "height": "2in"},
        }
    )
    presentation_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return presentation_path


def _run(capsys, *argv):
    exit_code = main(["--json", *argv])
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# --- result_version + schema conformance -----------------------------------


def test_validate_payload_conforms_and_is_versioned(minimal_deck_dir, capsys):
    code, out, _ = _run(capsys, "validate", str(minimal_deck_dir / "presentation.yaml"))
    assert code == EXIT_OK
    payload = json.loads(out)
    ValidateResult.model_validate(payload)
    assert payload["result_version"] == RESULT_VERSION == 1
    assert payload["warnings"] == []


def test_build_payload_conforms_and_lists_the_warning_without_a_manifest(
    minimal_deck_dir, tmp_path, capsys
):
    presentation = _warning_project(minimal_deck_dir, tmp_path, manifest=False)

    code, out, _ = _run(capsys, "build", str(presentation))

    assert code == EXIT_OK
    payload = json.loads(out)
    BuildResultPayload.model_validate(payload)
    # No `build.manifest` configured: the warning is still in the stdout JSON.
    assert payload["manifest"] is None
    assert payload["warning_count"] == 1 == len(payload["warnings"])
    (warning,) = payload["warnings"]
    assert warning["code"] == "W_MISSING_SIDECAR"
    assert "no reportifyr metadata sidecar" in warning["message"]
    assert warning["slide"] == "title"
    assert warning["element"] == "fig"


def test_build_warnings_match_the_manifest_when_one_is_written(minimal_deck_dir, tmp_path, capsys):
    presentation = _warning_project(minimal_deck_dir, tmp_path, manifest=True)

    _, out, _ = _run(capsys, "build", str(presentation))

    payload = json.loads(out)
    manifest = json.loads(Path(payload["manifest"]).read_text())
    # The manifest keeps its original shape (a list of message strings).
    assert manifest["warnings"] == [w["message"] for w in payload["warnings"]]


def test_build_artifacts_carry_paths_and_real_sha256(minimal_deck_dir, tmp_path, capsys):
    presentation = _copy_deck(minimal_deck_dir, tmp_path)

    _, out, _ = _run(capsys, "build", str(presentation))

    payload = json.loads(out)
    BuildResultPayload.model_validate(payload)
    by_kind = {a["kind"]: a for a in payload["artifacts"]}
    assert set(by_kind) == {"pptx", "manifest"}
    for artifact in payload["artifacts"]:
        assert artifact["sha256"] == hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()
    assert by_kind["pptx"]["path"] == payload["output"]
    assert by_kind["manifest"]["path"] == payload["manifest"]
    # The hash is also the one the manifest records for the output.
    manifest = json.loads(Path(payload["manifest"]).read_text())
    assert manifest["output"]["sha256"] == by_kind["pptx"]["sha256"]


def test_legacy_build_keys_are_unchanged(minimal_deck_dir, tmp_path, capsys):
    """The R facade and the web job manager read these; they must not move."""
    presentation = _copy_deck(minimal_deck_dir, tmp_path)
    _, out, _ = _run(capsys, "build", str(presentation))
    payload = json.loads(out)
    assert {"output", "manifest", "slide_count", "warning_count", "previews", "preview_pdf"} <= set(
        payload
    )
    assert isinstance(payload["warning_count"], int)


@requires_soffice
def test_preview_payload_conforms(minimal_deck_dir, tmp_path, capsys):
    presentation = _copy_deck(minimal_deck_dir, tmp_path)
    code, out, _ = _run(capsys, "preview", str(presentation))
    assert code == EXIT_OK
    payload = json.loads(out)
    PreviewResultPayload.model_validate(payload)
    kinds = [a["kind"] for a in payload["artifacts"]]
    assert kinds.count("preview") == len(payload["previews"]) == 2
    assert "preview_pdf" in kinds


def test_error_payload_is_versioned(tmp_path, capsys):
    code, out, err = _run(capsys, "validate", str(tmp_path / "missing.yaml"))
    assert code != EXIT_OK
    assert out == ""
    payload = json.loads(err)
    ErrorResult.model_validate(payload)
    assert payload["status"] == "error"
    assert payload["result_version"] == RESULT_VERSION


def test_missing_dependency_error_payload_conforms(minimal_deck_dir, tmp_path, capsys):
    presentation = _copy_deck(minimal_deck_dir, tmp_path)
    data = yaml.safe_load(presentation.read_text())
    data["build"]["preview"] = {"binary": "definitely-not-a-real-binary"}
    presentation.write_text(yaml.safe_dump(data, sort_keys=False))

    code, _, err = _run(capsys, "preview", str(presentation))

    assert code != EXIT_OK
    payload = json.loads(err)
    parsed = ErrorResult.model_validate(payload)
    assert parsed.code == "E_MISSING_DEPENDENCY"
    assert parsed.dependency is not None and parsed.dependency.name == "soffice"
    assert payload["result_version"] == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect", "{presentation}"],
        ["get", "{presentation}", "metadata.title"],
        ["slide", "list", "{presentation}"],
        ["schema", "design"],
    ],
    ids=["inspect", "get", "slide-list", "schema"],
)
def test_every_other_command_still_matches_the_generic_envelope(
    minimal_deck_dir, argv, capsys
):
    presentation = str(minimal_deck_dir / "presentation.yaml")
    code, out, _ = _run(capsys, *[a.format(presentation=presentation) for a in argv])
    assert code == EXIT_OK
    payload = json.loads(out)
    OkResult.model_validate(payload)
    assert payload["result_version"] == RESULT_VERSION


def test_build_warning_is_still_a_plain_string():
    """Existing consumers (manifest, `inspect`, tests) treat warnings as text."""
    from deckifyr.diagnostics import BuildWarning

    w = BuildWarning("LibreOffice is missing", "W_PREVIEW_SKIPPED").located("s1", "e1")
    assert isinstance(w, str) and "LibreOffice" in w
    assert json.dumps([w]) == '["LibreOffice is missing"]'
    assert w.located("other", "other").slide == "s1"  # fill-only
