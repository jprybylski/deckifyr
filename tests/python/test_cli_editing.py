import json
import shutil

import pytest
import yaml

from deckifyr.cli import EXIT_OK, EXIT_VALIDATION_ERROR, main


def _copy_minimal_deck(minimal_deck_dir, tmp_path):
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path


# --- get -------------------------------------------------------------


def test_get_reads_a_nested_value(minimal_deck_dir, capsys):
    exit_code = main(["--json", "get", str(minimal_deck_dir / "design.yaml"), "colors.primary"])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["value"] == "#2457A6"


def test_get_reports_path_not_found(minimal_deck_dir, capsys):
    exit_code = main(
        ["--json", "get", str(minimal_deck_dir / "design.yaml"), "colors.does-not-exist"]
    )
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_PATH_NOT_FOUND"


def test_get_reports_missing_file(capsys):
    exit_code = main(["--json", "get", "does/not/exist.yaml", "colors.primary"])
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_IO"


# --- set -------------------------------------------------------------


def test_set_writes_a_hex_color_without_quoting(minimal_deck_dir, tmp_path, capsys):
    # Regression coverage for the real bug hit while building this
    # feature: a bare "#123456" is a YAML comment opener, so the value
    # parser must not be a plain yaml.safe_load (see cli.py's
    # _parse_set_value docstring).
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    design_path = tmp_path / "design.yaml"

    exit_code = main(["--json", "set", str(design_path), "colors.primary", "#123456"])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["type"] == "design"

    data = yaml.safe_load(design_path.read_text())
    assert data["colors"]["primary"] == "#123456"


def test_set_parses_json_typed_values(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(["--json", "set", str(presentation_path), "build.previews", "true"])
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    assert data["build"]["previews"] is True


def test_set_string_flag_forces_literal_string(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        ["--json", "set", str(presentation_path), "metadata.status", "true", "--string"]
    )
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    assert data["metadata"]["status"] == "true"


def test_set_rejects_an_edit_that_breaks_schema_validation(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    design_path = tmp_path / "design.yaml"
    original = design_path.read_text()

    exit_code = main(["--json", "set", str(design_path), "fonts.body", "123"])
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_SCHEMA_VALIDATION"
    # A failed validation must never touch the file on disk.
    assert design_path.read_text() == original


def test_set_rejects_edit_that_introduces_a_dangling_layout_reference(
    minimal_deck_dir, tmp_path, capsys
):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        ["--json", "set", str(presentation_path), "slides[0].layout", "not-a-real-layout"]
    )
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_REFERENCE_NOT_FOUND"


# --- slide list/add/remove/update/move --------------------------------


def test_slide_list_reports_ids_and_layouts(minimal_deck_dir, capsys):
    exit_code = main(["--json", "slide", "list", str(minimal_deck_dir / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert [s["id"] for s in output["slides"]] == ["title", "content-slide"]


def test_slide_add_then_validate_round_trips(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        [
            "--json",
            "slide",
            "add",
            str(presentation_path),
            "--id",
            "new-slide",
            "--layout",
            "blank",
            "--notes",
            "speaker notes",
            "--after",
            "title",
        ]
    )
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["slide_count"] == 3

    data = yaml.safe_load(presentation_path.read_text())
    assert [s["id"] for s in data["slides"]] == ["title", "new-slide", "content-slide"]
    assert data["slides"][1]["notes"] == "speaker notes"

    exit_code = main(["--json", "validate", str(presentation_path)])
    assert exit_code == EXIT_OK
    capsys.readouterr()


def test_slide_add_accepts_elements_json(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    elements = json.dumps({"title": {"value": "A new title"}})
    exit_code = main(
        [
            "--json",
            "slide",
            "add",
            str(presentation_path),
            "--id",
            "new-slide",
            "--layout",
            "title-content",
            "--elements-json",
            elements,
        ]
    )
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    added = next(s for s in data["slides"] if s["id"] == "new-slide")
    assert added["elements"] == {"title": {"value": "A new title"}}


def test_slide_add_rejects_duplicate_id(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        ["--json", "slide", "add", str(presentation_path), "--id", "title"]
    )
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_CONTENT_VALIDATION"


def test_slide_remove_deletes_the_slide(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(["--json", "slide", "remove", str(presentation_path), "title"])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["slide_count"] == 1

    data = yaml.safe_load(presentation_path.read_text())
    assert [s["id"] for s in data["slides"]] == ["content-slide"]


def test_slide_remove_reports_unknown_id(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(["--json", "slide", "remove", str(presentation_path), "does-not-exist"])
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_REFERENCE_NOT_FOUND"


def test_slide_update_clears_layout_with_no_layout_flag(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        ["--json", "slide", "update", str(presentation_path), "title", "--no-layout"]
    )
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    title_slide = next(s for s in data["slides"] if s["id"] == "title")
    assert title_slide["layout"] is None


def test_slide_update_clears_notes_with_clear_notes_flag(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    main(["--json", "slide", "update", str(presentation_path), "title", "--notes", "hi"])
    capsys.readouterr()
    exit_code = main(
        ["--json", "slide", "update", str(presentation_path), "title", "--clear-notes"]
    )
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    title_slide = next(s for s in data["slides"] if s["id"] == "title")
    assert "notes" not in title_slide


def test_slide_move_reorders_slides(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    exit_code = main(
        [
            "--json",
            "slide",
            "move",
            str(presentation_path),
            "content-slide",
            "--before",
            "title",
        ]
    )
    assert exit_code == EXIT_OK
    capsys.readouterr()

    data = yaml.safe_load(presentation_path.read_text())
    assert [s["id"] for s in data["slides"]] == ["content-slide", "title"]


def test_slide_placement_flags_are_mutually_exclusive(minimal_deck_dir, tmp_path, capsys):
    _copy_minimal_deck(minimal_deck_dir, tmp_path)
    presentation_path = tmp_path / "presentation.yaml"

    # argparse's own mutually-exclusive-group usage error, not a
    # DeckifyrError -- argparse calls sys.exit(2) directly (exit code 2,
    # distinct from EXIT_VALIDATION_ERROR), which surfaces here as a
    # SystemExit rather than main()'s own return value.
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--json",
                "slide",
                "add",
                str(presentation_path),
                "--id",
                "x",
                "--after",
                "title",
                "--before",
                "content-slide",
            ]
        )
    assert exc_info.value.code == 2
