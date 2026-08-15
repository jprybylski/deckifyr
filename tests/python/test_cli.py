import json
import shutil
from pathlib import Path

from pptx import Presentation

from deckifyr.cli import EXIT_OK, EXIT_VALIDATION_ERROR, main


def test_validate_exits_ok_on_minimal_deck(minimal_deck_dir, capsys):
    exit_code = main(["--json", "validate", str(minimal_deck_dir / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["valid"] is True
    assert output["slide_count"] == 2


def test_build_writes_pptx_and_manifest(minimal_deck_dir, tmp_path, capsys):
    # Copy the fixture into tmp_path rather than building in place, so
    # this test doesn't leave a build/ directory inside the repo's
    # bundled example (the same fixture `deckifyr init` scaffolds from).
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)

    exit_code = main(["--json", "build", str(tmp_path / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["slide_count"] == 2

    prs = Presentation(output["output"])
    shape_names = {shape.name for slide in prs.slides for shape in slide.shapes}
    assert shape_names == {"deck-title", "title", "content"}

    manifest = json.loads(Path(output["manifest"]).read_text())
    assert manifest["slide_count"] == 2
    assert {"deckifyr_version", "elements", "input_files", "output"} <= manifest.keys()


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


def test_build_composes_a_color_derived_from_another_token(tmp_path, capsys):
    import colorsys

    (tmp_path / "design.yaml").write_text(
        "deckifyr: '0.1'\n"
        "slide: {width: 1in, height: 1in}\n"
        "fonts: {body: Arial, heading: Arial}\n"
        "colors:\n"
        "  primary: '#2457A6'\n"
        "  secondary:\n"
        "    base: primary\n"
        "    darken: 0.2\n"
        "text_styles:\n"
        "  derived:\n"
        "    font: body\n"
        "    size: 12pt\n"
        "    color: secondary\n"
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
        "    layout: null\n"
        "    elements:\n"
        "      - id: label\n"
        "        type: text\n"
        "        value: hi\n"
        "        style: derived\n"
        "        box: {x: 0in, y: 0in, width: 1in, height: 1in}\n"
    )

    exit_code = main(["--json", "build", str(tmp_path / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)

    r, g, b = (int("2457A6"[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    expected_rgb = colorsys.hls_to_rgb(h, max(0.0, l - 0.2), s)
    expected_hex = "".join(f"{round(c * 255):02X}" for c in expected_rgb)

    prs = Presentation(output["output"])
    (slide,) = list(prs.slides)
    (shape,) = list(slide.shapes)
    run = shape.text_frame.paragraphs[0].runs[0]
    assert str(run.font.color.rgb) == expected_hex


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
