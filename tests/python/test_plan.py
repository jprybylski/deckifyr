import pytest

from deckifyr.plan import expand_slide
from deckifyr.schema.design import (
    BrandingFurniture,
    DesignDocument,
    Fonts,
    Furniture,
    PageNumberFurniture,
    ShapeStyle,
    SlideSize,
    StatusFurniture,
    TextStyle,
)
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
        shape_styles={
            "card": ShapeStyle(fill="primary", line_color="text", line_width="2pt")
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


def test_slide_notes_pass_through_unresolved():
    design = _design()
    slide = Slide(id="s1", layout=None, elements=[], notes="Speaker notes go here.")
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.notes == "Speaker notes go here."


def test_slide_without_notes_resolves_to_none():
    design = _design()
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.notes is None


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
        elements=[Element(id="frag", type="quarto", value="x", box=_box())],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_table_element_is_supported():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="tbl", type="table", source="data.csv", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.type == "table"
    assert element.source == "data.csv"


def test_reportifyr_element_is_supported():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="fig",
                type="reportifyr",
                value="{rpfy}:conc-time.png",
                alt_text="a plot",
                box=_box(),
            )
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.type == "reportifyr"
    assert element.value == "{rpfy}:conc-time.png"


def test_reportifyr_element_footer_placement_defaults_to_below():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="fig",
                type="reportifyr",
                value="{rpfy}:conc-time.png",
                alt_text="a plot",
                box=_box(),
            )
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.footer_placement == "below"


def test_reportifyr_footer_placement_notes_is_honored():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="fig",
                type="reportifyr",
                value="{rpfy}:conc-time.png",
                alt_text="a plot",
                box=_box(),
                footer_placement="notes",
            )
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.footer_placement == "notes"


def test_rpfy_sourced_table_footer_placement_defaults_to_below():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(id="tbl", type="table", source="{rpfy}:pk-summary.csv", box=_box())
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.footer_placement == "below"


def test_footer_placement_rejected_on_plain_image_element():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="bg",
                type="image",
                source="bg.png",
                alt_text="bg",
                box=_box(),
                footer_placement="below",
            )
        ],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_footer_placement_rejected_on_plain_local_table():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="tbl",
                type="table",
                source="data.csv",
                box=_box(),
                footer_placement="below",
            )
        ],
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


def test_shape_element_resolves_kind_and_style():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(id="card", type="shape", shape_kind="rounded_rectangle", style="card", box=_box())
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.type == "shape"
    assert element.shape_kind == "rounded_rectangle"
    assert element.shape_style.fill == "#111111"
    assert element.shape_style.line_color == "#000000"
    assert element.shape_style.line_width_pt == pytest.approx(2.0)


def test_shape_without_kind_is_unfilled():
    design = _design()
    layout = Layout(elements={"deco": Element(type="shape", box=_box())})
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(slide, layout, design, strict=True)
    assert resolved.elements == []


def test_unknown_shape_style_raises():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(id="card", type="shape", shape_kind="oval", style="missing", box=_box())
        ],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_group_element_resolves_children_in_paint_order():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="card",
                type="group",
                box=_box(width="3in", height="2in"),
                elements=[
                    Element(id="front", type="text", value="front", z_index=5, box=_box()),
                    Element(id="back", type="shape", shape_kind="rectangle", z_index=1, box=_box()),
                ],
            )
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (group,) = resolved.elements
    assert group.type == "group"
    assert [child.id for child in group.children] == ["back", "front"]


def test_empty_group_is_unfilled():
    design = _design()
    layout = Layout(elements={"card": Element(type="group", box=_box())})
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(slide, layout, design, strict=True)
    assert resolved.elements == []


def test_group_child_without_id_in_list_form_raises():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="card",
                type="group",
                box=_box(),
                elements=[Element(type="text", value="hi", box=_box())],
            )
        ],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


# ---------------------------------------------------------------------------
# Document furniture (spec section 7.8)
# ---------------------------------------------------------------------------


def test_no_furniture_configured_expands_to_nothing_extra():
    design = _design()
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.elements == []


def test_background_image_synthesizes_a_full_bleed_image_behind_everything():
    design = _design(slide=SlideSize(width="10in", height="7.5in", background_image="bg.png"))
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="title", type="text", value="hi", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    ids = [e.id for e in resolved.elements]
    assert ids == ["__furniture_background", "title"]
    background = resolved.elements[0]
    assert background.type == "image"
    assert background.source == "bg.png"
    assert background.width == parse_length("10in", strict=True)
    assert background.height == parse_length("7.5in", strict=True)
    assert background.z_index < 0
    assert background.alt_text == "Background image"


def test_status_furniture_disabled_by_default():
    design = _design(
        furniture=Furniture(status=StatusFurniture(box=_box(), enabled=False))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.elements == []


def test_status_furniture_enabled_renders_its_text():
    design = _design(
        furniture=Furniture(status=StatusFurniture(box=_box(), enabled=True, text="DRAFT"))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.id == "__furniture_status"
    assert element.type == "text"
    assert element.value == "DRAFT"


def test_branding_furniture_presence_is_the_toggle():
    design = _design(furniture=Furniture(branding=BrandingFurniture(text="Acme / R&D", box=_box())))
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.id == "__furniture_branding"
    assert element.value == "Acme / R&D"


def test_page_number_substitutes_page_and_total():
    design = _design(furniture=Furniture(page_number=PageNumberFurniture(box=_box())))
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True, page_number=2, total_pages=5)
    (element,) = resolved.elements
    assert element.id == "__furniture_page_number"
    assert element.value == "2 / 5"


def test_page_number_custom_format():
    design = _design(
        furniture=Furniture(
            page_number=PageNumberFurniture(box=_box(), format="Page {page} of {total}")
        )
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True, page_number=3, total_pages=9)
    (element,) = resolved.elements
    assert element.value == "Page 3 of 9"


def test_page_number_unsupported_placeholder_raises():
    design = _design(
        furniture=Furniture(page_number=PageNumberFurniture(box=_box(), format="{author}"))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True, page_number=1, total_pages=1)


def test_page_number_disabled():
    design = _design(
        furniture=Furniture(page_number=PageNumberFurniture(box=_box(), enabled=False))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.elements == []


def test_slide_can_remove_a_furniture_element():
    design = _design(
        furniture=Furniture(status=StatusFurniture(box=_box(), enabled=True))
    )
    slide = Slide(id="s1", layout=None, elements={"__furniture_status": Element(remove=True)})
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.elements == []


def test_slide_can_override_a_furniture_elements_box():
    design = _design(
        furniture=Furniture(status=StatusFurniture(box=_box(), enabled=True))
    )
    slide = Slide(
        id="s1",
        layout=None,
        elements={"__furniture_status": Element(box=_box(width="4in"))},
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.width == parse_length("4in", strict=True)


def test_furniture_paints_behind_a_named_layouts_own_zones():
    design = _design(
        furniture=Furniture(branding=BrandingFurniture(text="Acme", box=_box()))
    )
    layout = Layout(elements={"title": Element(type="text", value="hi", box=_box())})
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(slide, layout, design, strict=True)
    assert [e.id for e in resolved.elements] == ["__furniture_branding", "title"]
