import json

import pytest
from PIL import Image
from pptx import Presentation

from deckifyr.plan import expand_presentation
from deckifyr.pptx.compose import _compute_image_placement, compose_and_write
from deckifyr.schema.design import DesignDocument, Fonts, SlideSize
from deckifyr.schema.errors import ContentValidationError
from deckifyr.schema.layouts import Box, Element, Layout, LayoutsDocument
from deckifyr.schema.presentation import (
    BuildConfig,
    DesignRef,
    Metadata,
    PresentationDocument,
    Slide,
)


def test_contain_letterboxes_and_centers():
    # 100x100 box, 200x100 (2:1) image -> width-limited, centered vertically.
    assert _compute_image_placement("contain", 100, 100, 200, 100) == (
        0, 25, 100, 50, 0.0, 0.0, 0.0, 0.0
    )


def test_cover_crops_the_long_axis():
    left, top, width, height, crop_left, crop_right, crop_top, crop_bottom = (
        _compute_image_placement("cover", 100, 100, 200, 100)
    )
    assert (left, top, width, height) == (0, 0, 100, 100)
    assert crop_left == crop_right == 0.25
    assert crop_top == crop_bottom == 0.0


def test_stretch_ignores_aspect_ratio():
    assert _compute_image_placement("stretch", 100, 50, 200, 100) == (
        0, 0, 100, 50, 0.0, 0.0, 0.0, 0.0
    )


def _design() -> DesignDocument:
    return DesignDocument(
        deckifyr="0.1",
        slide=SlideSize(width="10in", height="7.5in"),
        fonts=Fonts(body="Arial", heading="Arial"),
    )


def _presentation(*, alt_text: str | None = "a red rectangle") -> PresentationDocument:
    return PresentationDocument(
        deckifyr="0.1",
        design=DesignRef(base="design.yaml"),
        layouts="layouts.yaml",
        metadata=Metadata(title="Test"),
        build=BuildConfig(output="build/out.pptx", manifest="build/out.manifest.json"),
        slides=[
            Slide(
                id="s1",
                layout=None,
                elements=[
                    Element(
                        id="logo",
                        type="image",
                        source="logo.png",
                        alt_text=alt_text,
                        fit="contain",
                        box=Box(x="0in", y="0in", width="2in", height="1in"),
                    )
                ],
            )
        ],
    )


@pytest.fixture
def project(tmp_path):
    Image.new("RGB", (400, 200), color="red").save(tmp_path / "logo.png")
    (tmp_path / "design.yaml").write_text("design")
    (tmp_path / "layouts.yaml").write_text("layouts")
    (tmp_path / "presentation.yaml").write_text("presentation")
    return tmp_path


def _build(project, presentation, design):
    layouts = LayoutsDocument(deckifyr="0.1", layouts={})
    resolved = expand_presentation(presentation, design, layouts, strict=True)
    return compose_and_write(
        presentation,
        design,
        resolved,
        project_root=project,
        presentation_path=project / "presentation.yaml",
        design_path=project / "design.yaml",
        layouts_path=project / "layouts.yaml",
    )


def test_image_element_builds_and_manifest_records_its_source(project):
    result = _build(project, _presentation(), _design())

    assert result.output_path.is_file()
    prs = Presentation(str(result.output_path))
    (slide,) = list(prs.slides)
    (picture,) = list(slide.shapes)
    assert picture.name == "logo"

    manifest = json.loads(result.manifest_path.read_text())
    (element_entry,) = manifest["elements"]
    assert element_entry["element_id"] == "logo"
    assert element_entry["editability"] == "rendered_graphic"
    assert element_entry["resolved_path"].endswith("logo.png")
    assert "sha256" in element_entry


def test_missing_alt_text_raises(project):
    with pytest.raises(ContentValidationError):
        _build(project, _presentation(alt_text=None), _design())
