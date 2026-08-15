import pytest
import yaml
from pydantic import ValidationError

from deckifyr.schema.design import (
    Box,
    DesignDocument,
    Gradient,
    ShapeStyle,
    SlideSize,
    StatusFurniture,
    StatusIndicatorStyle,
    TextStyle,
)
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


def test_gradient_requires_at_least_two_stops():
    with pytest.raises(ValidationError):
        Gradient(stops=[{"color": "#FFFFFF", "position": 0.0}])


def test_gradient_stop_position_must_be_in_unit_range():
    with pytest.raises(ValidationError):
        Gradient(
            stops=[
                {"color": "#FFFFFF", "position": 0.0},
                {"color": "#000000", "position": 1.5},
            ]
        )


def test_slide_background_gradient_is_optional_and_parses():
    slide = SlideSize.model_validate(
        {
            "width": "10in",
            "height": "7.5in",
            "background_gradient": {
                "stops": [
                    {"color": "#F7FBFF", "position": 0.0},
                    {"color": "#DEEBF7", "position": 1.0},
                ],
                "angle": 135,
            },
        }
    )
    assert slide.background_gradient is not None
    assert [stop.color for stop in slide.background_gradient.stops] == ["#F7FBFF", "#DEEBF7"]
    assert slide.background_gradient.angle == 135

    bare = SlideSize(width="10in", height="7.5in")
    assert bare.background_gradient is None


def test_shape_style_fill_accepts_either_a_color_or_a_gradient():
    solid = ShapeStyle.model_validate({"fill": "primary"})
    assert solid.fill == "primary"

    gradient = ShapeStyle.model_validate(
        {
            "fill": {
                "stops": [
                    {"color": "primary", "position": 0.0},
                    {"color": "#FFFFFF", "position": 1.0},
                ]
            }
        }
    )
    assert isinstance(gradient.fill, Gradient)
    assert gradient.fill.angle == 90


def test_text_style_opacity_defaults_to_none_and_accepts_a_fraction():
    bare = TextStyle(font="body", size="12pt", color="text")
    assert bare.opacity is None

    faded = TextStyle(font="body", size="12pt", color="text", opacity=0.3)
    assert faded.opacity == 0.3


def test_text_style_opacity_must_be_in_unit_range():
    with pytest.raises(ValidationError):
        TextStyle(font="body", size="12pt", color="text", opacity=1.5)


def test_status_furniture_placements_default_to_none_and_accept_a_style():
    default = StatusFurniture()
    assert default.watermark is None
    assert default.corner_tr is None

    box = Box(x="0in", y="0in", width="1in", height="1in")
    configured = StatusFurniture(
        watermark=StatusIndicatorStyle(box=box, z_index=9999, rotation=-30),
        corner_br=StatusIndicatorStyle(box=box),
    )
    assert configured.watermark.z_index == 9999
    assert configured.watermark.rotation == -30
    assert configured.corner_br.z_index is None
    assert configured.corner_tr is None


def test_presentation_status_indicator_and_watermark_default_to_none():
    base_data = {
        "deckifyr": "0.1",
        "design": {"base": "design.yaml"},
        "layouts": "layouts.yaml",
        "metadata": {"title": "Watermark"},
        "build": {"output": "build/out.pptx"},
        "slides": [{"id": "a", "layout": None, "elements": []}],
    }
    unset = PresentationDocument.model_validate(base_data)
    assert unset.status_indicator is None
    assert unset.watermark is None

    configured = PresentationDocument.model_validate(
        {**base_data, "status_indicator": "corner-br", "watermark": "CONFIDENTIAL"}
    )
    assert configured.status_indicator == "corner-br"
    assert configured.watermark == "CONFIDENTIAL"


def test_presentation_watermark_mode_without_text_is_rejected():
    base_data = {
        "deckifyr": "0.1",
        "design": {"base": "design.yaml"},
        "layouts": "layouts.yaml",
        "metadata": {"title": "Watermark"},
        "build": {"output": "build/out.pptx"},
        "slides": [{"id": "a", "layout": None, "elements": []}],
    }
    with pytest.raises(ValidationError):
        PresentationDocument.model_validate({**base_data, "status_indicator": "watermark"})

    # A corner placement with no text is not an error at the schema
    # level -- deckifyr.plan simply skips it (no content, not required).
    PresentationDocument.model_validate({**base_data, "status_indicator": "corner-tl"})


def test_presentation_watermark_mode_falls_back_to_metadata_status():
    base_data = {
        "deckifyr": "0.1",
        "design": {"base": "design.yaml"},
        "layouts": "layouts.yaml",
        "metadata": {"title": "Watermark", "status": "demo"},
        "build": {"output": "build/out.pptx"},
        "slides": [{"id": "a", "layout": None, "elements": []}],
    }
    # No error: metadata.status supplies the text even with watermark unset.
    presentation = PresentationDocument.model_validate(
        {**base_data, "status_indicator": "watermark"}
    )
    assert presentation.watermark is None
    assert presentation.metadata.status == "demo"


def test_text_style_text_transform_defaults_to_none_and_accepts_uppercase():
    bare = TextStyle(font="body", size="12pt", color="text")
    assert bare.text_transform is None

    shouting = TextStyle(font="body", size="12pt", color="text", text_transform="uppercase")
    assert shouting.text_transform == "uppercase"

    with pytest.raises(ValidationError):
        TextStyle(font="body", size="12pt", color="text", text_transform="sideways")
