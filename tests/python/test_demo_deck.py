"""End-to-end coverage for examples/demo-deck (see its README.md): a
three-slide deck built from a real reportifyr-produced figure, not
placeholder content. This is a regression test for the whole
plan -> compose pipeline against a richer project than
inst/examples/minimal-deck's text/markdown-only fixture -- in
particular, it's the only test that builds a project with a multi-zone
layout, `rotation`, and `z_index` all at once.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pptx import Presentation
from pptx.oxml.ns import qn

from deckifyr.cli import EXIT_OK, main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_demo_deck(demo_deck_dir: Path, tmp_path: Path, capsys) -> dict:
    # Copy the whole project (including OUTPUTS/ and assets/, not just
    # the three YAML files) into tmp_path so the build's output doesn't
    # land inside the repo checkout.
    shutil.copytree(demo_deck_dir, tmp_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns("build"))

    exit_code = main(["--json", "build", str(tmp_path / "presentation.yaml")])
    assert exit_code == EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    return output


def _alt_text(picture_shape) -> str | None:
    cnv_pr = picture_shape._element.find(qn("p:nvPicPr")).find(qn("p:cNvPr"))
    return cnv_pr.get("descr")


def test_demo_deck_builds_three_slides_with_expected_shapes(demo_deck_dir, tmp_path, capsys):
    output = _build_demo_deck(demo_deck_dir, tmp_path, capsys)
    assert output["slide_count"] == 3

    prs = Presentation(output["output"])
    slides = list(prs.slides)
    assert len(slides) == 3

    furniture = {"__furniture_branding", "__furniture_page_number"}
    shape_names_per_slide = [{shape.name for shape in slide.shapes} for slide in slides]
    assert shape_names_per_slide == [
        {"deck-title", "deck-subtitle"} | furniture,
        {"title", "figure", "note"} | furniture,
        {"closing-title", "closing-note", "logo"} | furniture,
    ]


def test_demo_deck_figure_is_a_picture_with_alt_text(demo_deck_dir, tmp_path, capsys):
    output = _build_demo_deck(demo_deck_dir, tmp_path, capsys)
    prs = Presentation(output["output"])
    _title_slide, plot_slide, _closing_slide = list(prs.slides)

    figure = next(shape for shape in plot_slide.shapes if shape.name == "figure")
    assert figure.shape_type == 13  # MSO_SHAPE_TYPE.PICTURE
    assert "Theoph" in _alt_text(figure)


def test_demo_deck_logo_keeps_its_rotation(demo_deck_dir, tmp_path, capsys):
    output = _build_demo_deck(demo_deck_dir, tmp_path, capsys)
    prs = Presentation(output["output"])
    closing_slide = list(prs.slides)[2]

    logo = next(shape for shape in closing_slide.shapes if shape.name == "logo")
    # presentation.yaml sets rotation: -3; python-pptx normalizes negative
    # rotation to [0, 360), so -3 degrees clockwise reads back as 357.0.
    assert logo.rotation == 357.0
    assert _alt_text(logo) == "Organization logo"


def test_demo_deck_manifest_records_the_real_figure_hash(demo_deck_dir, tmp_path, capsys):
    output = _build_demo_deck(demo_deck_dir, tmp_path, capsys)
    manifest = json.loads(Path(output["manifest"]).read_text())

    assert manifest["slide_count"] == 3
    # 2 + 3 + 3 elements across the three slides, plus branding + page
    # number furniture (spec section 7.8) on each of them.
    assert len(manifest["elements"]) == 8 + 2 * 3

    figure_entry = next(
        e for e in manifest["elements"] if e["slide_id"] == "concentration-time" and e["element_id"] == "figure"
    )
    assert figure_entry["type"] == "image"
    assert figure_entry["editability"] == "rendered_graphic"
    resolved_path = Path(figure_entry["resolved_path"])
    assert resolved_path.is_file()
    assert figure_entry["sha256"] == _sha256(resolved_path)
    # The whole point of this fixture: the resolved figure is the actual
    # reportifyr-produced PNG shipped in examples/demo-deck/OUTPUTS/figures/,
    # not a placeholder generated for the test.
    assert figure_entry["sha256"] == _sha256(demo_deck_dir / "OUTPUTS" / "figures" / "conc-time.png")
