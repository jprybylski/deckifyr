import json

import pytest

from deckifyr.resolvers import BuildContext, ReportifyrResolver
from deckifyr.resolvers.reportifyr import (
    TextSegment,
    build_footer_lines,
    parse_magic_entries,
    split_scripts,
)
from deckifyr.schema.errors import ContentValidationError


def _write_artifact(tmp_path, *, name="conc-time.png", metadata=None, outputs_dir="OUTPUTS/figures"):
    outdir = tmp_path / outputs_dir
    outdir.mkdir(parents=True, exist_ok=True)
    artifact = outdir / name
    artifact.write_bytes(b"fake-png-bytes")
    if metadata is not None:
        stem, ext = name.rsplit(".", 1)
        sidecar = outdir / f"{stem}_{ext}_metadata.json"
        sidecar.write_text(json.dumps(metadata))
    return artifact


_METADATA = {
    "source_meta": {"path": "scripts/01_analysis.R", "latest_time": "2026-08-11 22:28:55"},
    "object_meta": {
        "meta_type": "conc-time-trajectories",
        "footnotes": {
            "equations": [],
            "notes": ["Data are from the built-in Theoph dataset."],
            "abbreviations": ["PK"],
        },
    },
}

_STANDARD_FOOTNOTES = {
    "figure_footnotes": {
        "conc-time-trajectories": "This plot shows individual concentration-time trajectories.",
    },
    "table_footnotes": {},
    "abbreviations": {
        "PK": "pharmacokinetic",
        "AUC_{0-24}": "area under the concentration-time curve from time 0 to 24 hours",
    },
}


# ---------------------------------------------------------------------------
# Magic-string parsing
# ---------------------------------------------------------------------------


def test_parse_single_entry():
    assert parse_magic_entries("{rpfy}:conc-time.png") == ["conc-time.png"]


def test_parse_bracket_list():
    assert parse_magic_entries("{rpfy}:[a.png, b.png]") == ["a.png", "b.png"]


def test_parse_ignores_per_entry_args():
    assert parse_magic_entries("{rpfy}:conc-time.png<width: 3in>") == ["conc-time.png"]
    assert parse_magic_entries("{rpfy}:[a.png<w: 1in>, b.png]") == ["a.png", "b.png"]


def test_parse_rejects_non_magic_string():
    with pytest.raises(ContentValidationError):
        parse_magic_entries("plain/path.png")


def test_parse_rejects_empty_magic_string():
    with pytest.raises(ContentValidationError):
        parse_magic_entries("{rpfy}:")


# ---------------------------------------------------------------------------
# Artifact resolution
# ---------------------------------------------------------------------------


def test_supports_only_magic_strings():
    resolver = ReportifyrResolver()
    assert resolver.supports("{rpfy}:conc-time.png") is True
    assert resolver.supports("OUTPUTS/figures/conc-time.png") is False


def test_resolves_single_artifact(tmp_path):
    artifact = _write_artifact(tmp_path, metadata=_METADATA)
    resolved = ReportifyrResolver().resolve(
        "{rpfy}:conc-time.png", BuildContext(project_root=str(tmp_path))
    )
    assert resolved.value.path == artifact
    assert resolved.value.metadata["object_meta"]["meta_type"] == "conc-time-trajectories"
    assert resolved.value.warnings == []


def test_multi_figure_uses_first_and_warns(tmp_path):
    _write_artifact(tmp_path, name="a.png", metadata=_METADATA)
    _write_artifact(tmp_path, name="b.png", metadata=_METADATA)
    resolved = ReportifyrResolver().resolve(
        "{rpfy}:[a.png, b.png]", BuildContext(project_root=str(tmp_path))
    )
    assert resolved.value.path.name == "a.png"
    assert len(resolved.value.warnings) == 1
    assert "a.png" in resolved.value.warnings[0] and "b.png" in resolved.value.warnings[0]


def test_artifact_not_found_raises(tmp_path):
    (tmp_path / "OUTPUTS").mkdir()
    with pytest.raises(ContentValidationError):
        ReportifyrResolver().resolve(
            "{rpfy}:missing.png", BuildContext(project_root=str(tmp_path))
        )


def test_missing_outputs_dir_raises(tmp_path):
    with pytest.raises(ContentValidationError):
        ReportifyrResolver().resolve(
            "{rpfy}:conc-time.png", BuildContext(project_root=str(tmp_path))
        )


def test_duplicate_artifact_raises(tmp_path):
    _write_artifact(tmp_path, outputs_dir="OUTPUTS/figures")
    _write_artifact(tmp_path, outputs_dir="OUTPUTS/tables")
    with pytest.raises(ContentValidationError):
        ReportifyrResolver().resolve(
            "{rpfy}:conc-time.png", BuildContext(project_root=str(tmp_path))
        )


def test_missing_sidecar_fails_by_default(tmp_path):
    _write_artifact(tmp_path, metadata=None)
    with pytest.raises(ContentValidationError):
        ReportifyrResolver().resolve(
            "{rpfy}:conc-time.png", BuildContext(project_root=str(tmp_path))
        )


def test_missing_sidecar_warns_when_not_failing(tmp_path):
    _write_artifact(tmp_path, metadata=None)
    resolved = ReportifyrResolver(fail_on_missing_metadata=False).resolve(
        "{rpfy}:conc-time.png", BuildContext(project_root=str(tmp_path))
    )
    assert resolved.value.metadata is None
    assert len(resolved.value.warnings) == 1


# ---------------------------------------------------------------------------
# Footer text
# ---------------------------------------------------------------------------


def test_build_footer_lines():
    lines = build_footer_lines(_METADATA, "figure", _STANDARD_FOOTNOTES)
    assert lines == [
        "Source: scripts/01_analysis.R 2026-08-11 22:28:55",
        "Notes: This plot shows individual concentration-time trajectories. "
        "Data are from the built-in Theoph dataset.",
        "Abbreviations: PK: pharmacokinetic.",
    ]


def test_build_footer_lines_missing_meta_type_raises():
    metadata = {
        "object_meta": {"meta_type": "not-a-real-type", "footnotes": {"notes": [], "abbreviations": []}}
    }
    with pytest.raises(ContentValidationError):
        build_footer_lines(metadata, "figure", _STANDARD_FOOTNOTES)


def test_build_footer_lines_missing_abbreviation_raises():
    metadata = {
        "object_meta": {
            "meta_type": None,
            "footnotes": {"notes": [], "abbreviations": ["NOT_DEFINED"]},
        }
    }
    with pytest.raises(ContentValidationError):
        build_footer_lines(metadata, "figure", _STANDARD_FOOTNOTES)


def test_build_footer_lines_table_uses_table_footnotes():
    metadata = {
        "object_meta": {
            "meta_type": "univariate",
            "footnotes": {"notes": [], "abbreviations": []},
        }
    }
    standard_footnotes = {
        "table_footnotes": {"univariate": "The p-value is from the likelihood ratio test."},
        "abbreviations": {},
    }
    lines = build_footer_lines(metadata, "table", standard_footnotes)
    assert lines == ["Notes: The p-value is from the likelihood ratio test."]


# ---------------------------------------------------------------------------
# Subscript/superscript notation
# ---------------------------------------------------------------------------


def test_split_scripts_plain_text():
    assert split_scripts("PK: pharmacokinetic") == [TextSegment("PK: pharmacokinetic")]


def test_split_scripts_subscript_and_superscript():
    segments = split_scripts("AUC_{0-24} and X^{2}")
    assert segments == [
        TextSegment("AUC"),
        TextSegment("0-24", "sub"),
        TextSegment(" and X"),
        TextSegment("2", "sup"),
    ]
