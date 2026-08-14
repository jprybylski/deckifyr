import pytest

from deckifyr.plan import expand_slide
from deckifyr.schema.design import DesignDocument, Fonts, SlideSize, TextStyle
from deckifyr.schema.errors import ContentValidationError
from deckifyr.schema.layouts import Box, Element, Layout
from deckifyr.schema.presentation import Slide
from deckifyr.schema.units import parse_length


def _design(**overrides):
    data = dict(
        deckifyr="0.1",
        slide=SlideSize(width="10in", height="7.5in"),
        fonts=Fonts(body="Arial", heading="Arial"),
        colors={"text": "#000000", "primary": "#111111"},
        text_styles={
            "title": TextStyle(font="heading", size="20pt", bold=True, color="primary")
        },
    )
    data.update(overrides)
    return DesignDocument(**data)


def _box(**overrides):
    data = dict(x="0in", y="0in", width="1in", height="1in")
    data.update(overrides)
    return Box(**data)


def test_required_zone_without_override_raises():
    design = _design()
    layout = Layout(
        elements={"title": Element(type="text", box=_box(), required=True)}
    )
    slide = Slide(id="s1", layout="main", elements={})
    with pytest.raises(ContentValidationError):
        expand_slide(slide, layout, design, strict=True)


def test_unfilled_optional_zone_is_skipped():
    design = _design()
    layout = Layout(elements={"content": Element(type="slot", box=_box())})
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(slide, layout, design, strict=True)
    assert resolved.elements == []


def test_remove_drops_a_layout_element():
    design = _design()
    layout = Layout(elements={"footer": Element(type="text", value="hi", box=_box())})
    slide = Slide(id="s1", layout="main", elements={"footer": Element(remove=True)})
    resolved = expand_slide(slide, layout, design, strict=True)
    assert resolved.elements == []


def test_slide_override_merges_onto_layout_zone():
    design = _design()
    layout = Layout(elements={"content": Element(type="slot", box=_box(width="2in"))})
    slide = Slide(
        id="s1", layout="main", elements={"content": Element(type="markdown", value="hello")}
    )
    resolved = expand_slide(slide, layout, design, strict=True)
    assert len(resolved.elements) == 1
    element = resolved.elements[0]
    assert element.type == "markdown"
    assert element.value == "hello"
    assert element.width == parse_length("2in", strict=True)


def test_freeform_slide_uses_list_elements_with_their_own_ids():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(id="bg", type="image", source="bg.png", alt_text="bg", box=_box())
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    assert [e.id for e in resolved.elements] == ["bg"]


def test_z_index_sorts_elements_for_paint_order():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(id="front", type="text", value="front", z_index=5, box=_box()),
            Element(id="back", type="text", value="back", z_index=1, box=_box()),
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    assert [e.id for e in resolved.elements] == ["back", "front"]


def test_unsupported_element_type_raises():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="tbl", type="table", value="x", box=_box())],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_style_token_resolves_font_and_color():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="t", type="text", value="hi", style="title", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    style = resolved.elements[0].style
    assert style.font == "Arial"
    assert style.color == "#111111"
    assert style.bold is True
