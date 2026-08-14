import pytest
import yaml
from pydantic import ValidationError

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument


def _load(path):
    return yaml.safe_load(path.read_text())


def test_minimal_deck_design_validates(minimal_deck_dir):
    design = DesignDocument.model_validate(_load(minimal_deck_dir / "design.yaml"))
    assert design.deckifyr == "0.1"
    assert design.slide.width == "13.333in"


def test_minimal_deck_layouts_validates(minimal_deck_dir):
    layouts = LayoutsDocument.model_validate(_load(minimal_deck_dir / "layouts.yaml"))
    assert set(layouts.layouts) == {"title-content", "blank"}
    assert layouts.layouts["title-content"].elements["title"].required is True


def test_minimal_deck_presentation_validates(minimal_deck_dir):
    presentation = PresentationDocument.model_validate(
        _load(minimal_deck_dir / "presentation.yaml")
    )
    assert [slide.id for slide in presentation.slides] == ["title", "content-slide"]
    assert presentation.slides[0].layout == "blank"


def test_presentation_rejects_duplicate_slide_ids():
    data = {
        "deckifyr": "0.1",
        "design": {"base": "design.yaml"},
        "layouts": "layouts.yaml",
        "metadata": {"title": "Dup"},
        "build": {"output": "build/out.pptx"},
        "slides": [
            {"id": "a", "layout": None, "elements": []},
            {"id": "a", "layout": None, "elements": []},
        ],
    }
    with pytest.raises(ValidationError):
        PresentationDocument.model_validate(data)


def test_slide_notes_defaults_to_none_and_accepts_text():
    data = {
        "deckifyr": "0.1",
        "design": {"base": "design.yaml"},
        "layouts": "layouts.yaml",
        "metadata": {"title": "Notes"},
        "build": {"output": "build/out.pptx"},
        "slides": [
            {"id": "a", "layout": None, "elements": []},
            {"id": "b", "layout": None, "elements": [], "notes": "Remember to mention Q3."},
        ],
    }
    presentation = PresentationDocument.model_validate(data)
    assert presentation.slides[0].notes is None
    assert presentation.slides[1].notes == "Remember to mention Q3."


def test_unsupported_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        DesignDocument.model_validate(
            {
                "deckifyr": "99.9",
                "slide": {"width": "1in", "height": "1in"},
                "fonts": {"body": "Arial", "heading": "Arial"},
            }
        )
