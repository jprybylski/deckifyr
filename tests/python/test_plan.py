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
    StatusIndicatorStyle,
    TableStyle,
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
        elements=[Element(id="frag", type="footnotes", value="x", box=_box())],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_quarto_element_is_supported():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="frag", type="quarto", source="fragments/interp.qmd", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.type == "quarto"
    assert element.source == "fragments/interp.qmd"


def test_quarto_element_requires_source_not_value():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="frag", type="quarto", value="inline text", box=_box())],
    )
    with pytest.raises(ContentValidationError, match="requires a 'source'"):
        expand_slide(slide, None, design, strict=True)


def test_quarto_element_source_must_be_qmd():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="frag", type="quarto", source="not-a-fragment.txt", box=_box())],
    )
    with pytest.raises(ContentValidationError, match="must be a .qmd file"):
        expand_slide(slide, None, design, strict=True)


def test_quarto_element_render_mode_defaults_to_auto():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="frag", type="quarto", source="fragments/interp.qmd", box=_box())],
    )
    (element,) = expand_slide(slide, None, design, strict=True).elements
    assert element.render_mode == "auto"


def test_quarto_element_style_resolves_like_text():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="frag",
                type="quarto",
                source="fragments/interp.qmd",
                style="title",
                box=_box(),
            )
        ],
    )
    (element,) = expand_slide(slide, None, design, strict=True).elements
    assert element.style is not None
    assert element.style.bold is True


def test_other_element_types_still_default_render_mode_to_native():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="txt", type="text", value="hi", box=_box())],
    )
    (element,) = expand_slide(slide, None, design, strict=True).elements
    assert element.render_mode == "native"


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


def test_table_style_resolves_color_tokens_and_border_width():
    design = _design(
        table_styles={
            "branded": TableStyle(
                header_fill="primary",
                header_text_color="#FFFFFF",
                body_fill="#FFFFFF",
                band_fill="#EEEEEE",
                border_color="text",
                border_width="1.5pt",
            )
        }
    )
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="tbl",
                type="table",
                source="data.csv",
                table_style="branded",
                box=_box(),
            )
        ],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.table_style.header_fill == "#111111"
    assert element.table_style.header_text_color == "#FFFFFF"
    assert element.table_style.body_fill == "#FFFFFF"
    assert element.table_style.band_fill == "#EEEEEE"
    assert element.table_style.border_color == "#000000"
    assert element.table_style.border_width_pt == pytest.approx(1.5)


def test_table_style_unset_leaves_table_style_none():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="tbl", type="table", source="data.csv", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.table_style is None


def test_unknown_table_style_raises():
    design = _design()
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="tbl", type="table", source="data.csv", table_style="nope", box=_box()
            )
        ],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_table_style_rejected_on_non_table_element():
    design = _design(
        table_styles={"branded": TableStyle(header_fill="primary")}
    )
    slide = Slide(
        id="s1",
        layout=None,
        elements=[
            Element(
                id="txt",
                type="text",
                value="hi",
                table_style="branded",
                box=_box(),
            )
        ],
    )
    with pytest.raises(ContentValidationError):
        expand_slide(slide, None, design, strict=True)


def test_table_style_falls_back_to_design_default():
    design = _design(
        table_styles={"branded": TableStyle(header_fill="primary")},
    )
    design = design.model_copy(update={"defaults": design.defaults.model_copy(update={"table_style": "branded"})})
    slide = Slide(
        id="s1",
        layout=None,
        elements=[Element(id="tbl", type="table", source="data.csv", box=_box())],
    )
    resolved = expand_slide(slide, None, design, strict=True)
    (element,) = resolved.elements
    assert element.table_style.header_fill == "#111111"


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


def test_status_indicator_unset_renders_nothing_even_if_design_configures_it():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(slide, None, design, strict=True)
    assert resolved.elements == []


def test_status_indicator_none_renders_nothing():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="none", watermark_text="DRAFT"
    )
    assert resolved.elements == []


def test_status_indicator_watermark_renders_the_watermark_text():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    (element,) = resolved.elements
    assert element.id == "__furniture_status"
    assert element.type == "text"
    assert element.value == "DRAFT"
    assert element.center is True


def test_status_indicator_corner_selects_its_own_placement():
    design = _design(
        furniture=Furniture(
            status=StatusFurniture(
                watermark=StatusIndicatorStyle(box=_box(width="9in")),
                corner_br=StatusIndicatorStyle(box=_box(x="8in", y="6.5in")),
            )
        )
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="corner-br", watermark_text="DRAFT"
    )
    (element,) = resolved.elements
    assert element.x == parse_length("8in", strict=True)
    assert element.width == parse_length("1in", strict=True)  # from _box()'s own default


def test_status_indicator_with_no_design_placement_raises():
    design = _design(furniture=Furniture(status=StatusFurniture()))
    slide = Slide(id="s1", layout=None, elements=[])
    with pytest.raises(ContentValidationError):
        expand_slide(
            slide, None, design, strict=True, status_indicator="corner-tl", watermark_text="DRAFT"
        )


def test_status_indicator_corner_with_no_watermark_text_is_skipped_not_an_error():
    design = _design(
        furniture=Furniture(status=StatusFurniture(corner_tl=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="corner-tl", watermark_text=None
    )
    assert resolved.elements == []


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
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements={"__furniture_status": Element(remove=True)})
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    assert resolved.elements == []


def test_slide_can_override_a_furniture_elements_box():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(
        id="s1",
        layout=None,
        elements={"__furniture_status": Element(box=_box(width="4in"))},
    )
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
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


def test_status_indicator_rotation_flows_to_the_resolved_element():
    design = _design(
        furniture=Furniture(
            status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box(), rotation=-30))
        )
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    (element,) = resolved.elements
    assert element.rotation == -30


@pytest.mark.parametrize(
    "field_name, status_indicator, expected_align",
    [
        ("corner_tr", "corner-tr", "right"),
        ("corner_br", "corner-br", "right"),
        ("corner_tl", "corner-tl", "left"),
        ("corner_bl", "corner-bl", "left"),
    ],
)
def test_status_indicator_corner_align_depends_on_which_edge(
    field_name, status_indicator, expected_align
):
    design = _design(
        furniture=Furniture(
            status=StatusFurniture(**{field_name: StatusIndicatorStyle(box=_box())})
        )
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide,
        None,
        design,
        strict=True,
        status_indicator=status_indicator,
        watermark_text="DRAFT",
    )
    (element,) = resolved.elements
    assert element.align == expected_align


def test_status_indicator_watermark_has_no_forced_align():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    (element,) = resolved.elements
    assert element.align is None


def test_status_indicator_z_index_defaults_to_the_overlay_constant():
    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    slide = Slide(id="s1", layout=None, elements=[])
    resolved = expand_slide(
        slide, None, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    (element,) = resolved.elements
    assert element.z_index < 0


def test_status_indicator_z_index_override_paints_on_top_of_ordinary_content():
    design = _design(
        furniture=Furniture(
            status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box(), z_index=9999))
        )
    )
    layout = Layout(elements={"title": Element(type="text", value="hi", box=_box())})
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(
        slide, layout, design, strict=True, status_indicator="watermark", watermark_text="DRAFT"
    )
    # Ordinary elements default to z_index 0; the watermark's explicit
    # 9999 must sort after it, i.e. paint on top.
    assert [e.id for e in resolved.elements] == ["title", "__furniture_status"]


def test_resolve_text_style_passes_opacity_through():
    design = _design(
        text_styles={
            "watermark": TextStyle(font="heading", size="20pt", color="primary", opacity=0.3)
        }
    )
    from deckifyr.plan import resolve_text_style

    style = resolve_text_style(design, "watermark")
    assert style.opacity == 0.3


def test_resolve_text_style_passes_text_transform_through():
    design = _design(
        text_styles={
            "watermark": TextStyle(
                font="heading", size="20pt", color="primary", text_transform="uppercase"
            )
        }
    )
    from deckifyr.plan import resolve_text_style

    style = resolve_text_style(design, "watermark")
    assert style.text_transform == "uppercase"


def test_resolve_text_style_opacity_defaults_to_none():
    design = _design()
    from deckifyr.plan import resolve_text_style

    style = resolve_text_style(design, "title")
    assert style.opacity is None


def test_expand_presentation_threads_status_indicator_and_watermark_through():
    from deckifyr.plan import expand_presentation
    from deckifyr.schema.layouts import LayoutsDocument
    from deckifyr.schema.presentation import BuildConfig, DesignRef, Metadata
    from deckifyr.schema.presentation import PresentationDocument

    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    layouts = LayoutsDocument(deckifyr="0.1", layouts={})
    presentation = PresentationDocument(
        deckifyr="0.1",
        design=DesignRef(base="design.yaml"),
        layouts="layouts.yaml",
        metadata=Metadata(title="T"),
        build=BuildConfig(output="build/out.pptx"),
        status_indicator="watermark",
        watermark="DRAFT",
        slides=[Slide(id="s1", layout=None, elements=[])],
    )
    (resolved_slide,) = expand_presentation(presentation, design, layouts, strict=True)
    assert [e.id for e in resolved_slide.elements] == ["__furniture_status"]
    assert resolved_slide.elements[0].value == "DRAFT"


def test_expand_presentation_falls_back_to_metadata_status_when_watermark_unset():
    from deckifyr.plan import expand_presentation
    from deckifyr.schema.layouts import LayoutsDocument
    from deckifyr.schema.presentation import BuildConfig, DesignRef, Metadata
    from deckifyr.schema.presentation import PresentationDocument

    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    layouts = LayoutsDocument(deckifyr="0.1", layouts={})
    presentation = PresentationDocument(
        deckifyr="0.1",
        design=DesignRef(base="design.yaml"),
        layouts="layouts.yaml",
        metadata=Metadata(title="T", status="demo"),
        build=BuildConfig(output="build/out.pptx"),
        status_indicator="watermark",
        watermark=None,
        slides=[Slide(id="s1", layout=None, elements=[])],
    )
    (resolved_slide,) = expand_presentation(presentation, design, layouts, strict=True)
    (element,) = resolved_slide.elements
    assert element.value == "demo"


def test_expand_presentation_explicit_watermark_overrides_metadata_status():
    from deckifyr.plan import expand_presentation
    from deckifyr.schema.layouts import LayoutsDocument
    from deckifyr.schema.presentation import BuildConfig, DesignRef, Metadata
    from deckifyr.schema.presentation import PresentationDocument

    design = _design(
        furniture=Furniture(status=StatusFurniture(watermark=StatusIndicatorStyle(box=_box())))
    )
    layouts = LayoutsDocument(deckifyr="0.1", layouts={})
    presentation = PresentationDocument(
        deckifyr="0.1",
        design=DesignRef(base="design.yaml"),
        layouts="layouts.yaml",
        metadata=Metadata(title="T", status="demo"),
        build=BuildConfig(output="build/out.pptx"),
        status_indicator="watermark",
        watermark="CONFIDENTIAL",
        slides=[Slide(id="s1", layout=None, elements=[])],
    )
    (resolved_slide,) = expand_presentation(presentation, design, layouts, strict=True)
    (element,) = resolved_slide.elements
    assert element.value == "CONFIDENTIAL"


# ---------------------------------------------------------------------------
# Gradients
# ---------------------------------------------------------------------------


def test_resolve_gradient_resolves_stop_color_tokens():
    from deckifyr.plan import resolve_gradient
    from deckifyr.schema.design import Gradient, GradientStop

    design = _design()
    gradient = Gradient(
        stops=[
            GradientStop(color="primary", position=0.0),
            GradientStop(color="#FFFFFF", position=1.0),
        ],
        angle=135,
    )
    resolved = resolve_gradient(design, gradient)
    assert [stop.color for stop in resolved.stops] == ["#111111", "#FFFFFF"]
    assert [stop.position for stop in resolved.stops] == [0.0, 1.0]
    assert resolved.angle == 135


def test_shape_style_gradient_fill_resolves_to_a_resolved_gradient():
    from deckifyr.plan import ResolvedGradient
    from deckifyr.schema.design import Gradient, GradientStop, ShapeStyle

    design = _design(
        shape_styles={
            "card": ShapeStyle(
                fill=Gradient(
                    stops=[
                        GradientStop(color="primary", position=0.0),
                        GradientStop(color="text", position=1.0),
                    ]
                )
            )
        }
    )
    layout = Layout(
        elements={
            "box": Element(type="shape", shape_kind="rectangle", box=_box(), style="card")
        }
    )
    slide = Slide(id="s1", layout="main", elements={})
    resolved = expand_slide(slide, layout, design, strict=True)
    (element,) = resolved.elements
    assert isinstance(element.shape_style.fill, ResolvedGradient)
    assert [stop.color for stop in element.shape_style.fill.stops] == ["#111111", "#000000"]
