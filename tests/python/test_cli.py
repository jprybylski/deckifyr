import json

from deckifyr.cli import EXIT_NOT_IMPLEMENTED, EXIT_OK, EXIT_VALIDATION_ERROR, main


def test_validate_exits_ok_on_minimal_deck(minimal_deck_dir, capsys):
    exit_code = main(["--json", "validate", str(minimal_deck_dir / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["valid"] is True
    assert output["slide_count"] == 2


def test_build_is_not_implemented_yet(minimal_deck_dir, capsys):
    exit_code = main(["--json", "build", str(minimal_deck_dir / "presentation.yaml")])
    assert exit_code == EXIT_NOT_IMPLEMENTED
    # Errors go to stderr, not stdout -- see cli.py's main() comment on
    # why (the R facade's pyro bridge depends on this split).
    output = json.loads(capsys.readouterr().err)
    assert output["status"] == "error"
    assert output["code"] == "E_NOT_IMPLEMENTED"


def test_validate_reports_missing_file(capsys):
    exit_code = main(["--json", "validate", "does/not/exist.yaml"])
    assert exit_code != EXIT_OK
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_IO"


def test_validate_rejects_unknown_layout_reference(tmp_path, capsys):
    (tmp_path / "design.yaml").write_text(
        "deckifyr: '0.1'\n"
        "slide: {width: 1in, height: 1in}\n"
        "fonts: {body: Arial, heading: Arial}\n"
    )
    (tmp_path / "layouts.yaml").write_text("deckifyr: '0.1'\nlayouts: {}\n")
    (tmp_path / "presentation.yaml").write_text(
        "deckifyr: '0.1'\n"
        "design: {base: design.yaml}\n"
        "layouts: layouts.yaml\n"
        "metadata: {title: Test}\n"
        "build: {output: build/out.pptx}\n"
        "slides:\n"
        "  - id: only-slide\n"
        "    layout: does-not-exist\n"
        "    elements: {}\n"
    )
    exit_code = main(["--json", "validate", str(tmp_path / "presentation.yaml")])
    assert exit_code == EXIT_VALIDATION_ERROR
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "E_REFERENCE_NOT_FOUND"


def test_schema_command_prints_json_schema(capsys):
    exit_code = main(["schema", "presentation"])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["title"] == "PresentationDocument"


def test_init_scaffolds_a_new_project(tmp_path):
    target = tmp_path / "new-project"
    exit_code = main(["--json", "init", str(target)])
    assert exit_code == EXIT_OK
    assert (target / "design.yaml").is_file()
    assert (target / "layouts.yaml").is_file()
    assert (target / "presentation.yaml").is_file()


def test_init_refuses_nonempty_directory_without_force(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "stray.txt").write_text("hi")
    exit_code = main(["--json", "init", str(target)])
    assert exit_code != EXIT_OK
