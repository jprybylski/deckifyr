"""Pass 1: plan and shell expansion (spec section 6).

Turns a validated `PresentationDocument` + `DesignDocument` +
`LayoutsDocument` into a list of `ResolvedSlide`/`ResolvedElement`
objects: logical layouts expanded onto slides, style tokens resolved,
and geometry converted to EMU. This module deliberately has no
`python-pptx` import -- spec section 6 keeps "plan and shell" and
"resolve and compose" as separate stages specifically so a shell can be
inspected or cached independent of whatever consumes it (today, only
`deckifyr.pptx`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import ContentValidationError
from deckifyr.schema.layouts import Box, Element, Layout, LayoutsDocument
from deckifyr.schema.merge import deep_merge
from deckifyr.schema.presentation import PresentationDocument, Slide
from deckifyr.schema.units import EMU_PER_POINT, parse_length

# Element types this slice's compositor can actually place on a slide.
# Everything else in spec section 7.7's `type` enum (table, quarto,
# reportifyr) is later-phase work (deckifyr-specification.md section 18)
# -- raising a clear error here keeps that boundary explicit instead of
# silently dropping content (spec section 20 warning 7).
SUPPORTED_ELEMENT_TYPES = {"text", "markdown", "image", "shape", "group"}

# Reserved ids for `design.yaml`'s `furniture` block (spec section 7.8),
# synthesized fresh per slide by `_furniture_layout` below. The
# `__furniture_` prefix keeps these out of the way of author-chosen zone/
# element ids, so the ordinary duplicate-id check in
# `_iter_slide_element_pairs` is a non-issue in practice.
_FURNITURE_BACKGROUND_ID = "__furniture_background"
_FURNITURE_STATUS_ID = "__furniture_status"
_FURNITURE_BRANDING_ID = "__furniture_branding"
_FURNITURE_PAGE_NUMBER_ID = "__furniture_page_number"

# Furniture must never obscure real slide content by default (spec
# section 7.8), so it paints well behind the implicit `z_index: 0` every
# ordinary element defaults to -- the background furthest back of all.
_FURNITURE_BACKGROUND_Z_INDEX = -1000
_FURNITURE_OVERLAY_Z_INDEX = -10

# `_add_image_shape` (deckifyr.pptx.compose) requires alt_text on every
# image; a furniture background is decorative branding, not authored
# content, so it gets one fixed description rather than a config field.
_FURNITURE_BACKGROUND_ALT_TEXT = "Background image"


@dataclass
class ResolvedTextStyle:
    """A `design.yaml` text style with its `font`/`color` tokens already
    resolved to literal values (spec section 7.4's `fonts:`/`colors:`
    blocks) -- the compositor should never need `design` again to render
    a resolved element's text.
    """

    font: str
    size_pt: float
    bold: bool
    italic: bool
    color: str


@dataclass
class ResolvedShapeStyle:
    """A `design.yaml` shape style with its `fill`/`line_color` tokens
    already resolved to literal values, mirroring `ResolvedTextStyle`.
    Any field left `None` here means "use `deckifyr.pptx.compose`'s own
    default", not "no style" -- that distinction is only meaningful at
    `design.yaml`'s `ShapeStyle` level.
    """

    fill: str | None
    line_color: str | None
    line_width_pt: float | None


@dataclass
class ResolvedElement:
    id: str
    type: str
    value: Any
    source: str | None
    x: int
    y: int
    width: int
    height: int
    rotation: float
    z_index: int
    order: int  # declaration order, used as a z-order tiebreaker
    style: ResolvedTextStyle | None
    fit: str
    overflow: str
    render_mode: str
    alt_text: str | None
    required: bool
    shape_kind: str | None = None
    shape_style: ResolvedShapeStyle | None = None
    # `group`-only: already-resolved children, sorted by paint order the
    # same way `ResolvedSlide.elements` is.
    children: list["ResolvedElement"] = field(default_factory=list)


@dataclass
class ResolvedSlide:
    id: str
    elements: list[ResolvedElement] = field(default_factory=list)


def _resolve_text_style(
    design: DesignDocument, style_name: str | None
) -> ResolvedTextStyle | None:
    if style_name is None:
        return None
    style = design.text_styles.get(style_name)
    if style is None:
        raise ContentValidationError(
            f"unknown style {style_name!r}: not defined in design.yaml's "
            "text_styles"
        )

    fonts = design.fonts.model_dump()
    # A style's `font`/`color` may name a design token (spec section 7.4's
    # `fonts.heading`/`colors.primary`) or, since both fields are plain
    # strings in the schema, a literal value directly -- token lookup
    # falls back to the literal when there's no matching token, rather
    # than erroring, since `design.slide.background` already uses bare
    # hex literals with no token indirection at all.
    font = fonts.get(style.font, style.font)
    color = design.colors.get(style.color, style.color)
    size_pt = parse_length(style.size, strict=True) / EMU_PER_POINT

    return ResolvedTextStyle(
        font=font, size_pt=size_pt, bold=style.bold, italic=style.italic, color=color
    )


def _resolve_shape_style(
    design: DesignDocument, style_name: str | None
) -> ResolvedShapeStyle | None:
    if style_name is None:
        return None
    style = design.shape_styles.get(style_name)
    if style is None:
        raise ContentValidationError(
            f"unknown style {style_name!r}: not defined in design.yaml's "
            "shape_styles"
        )

    fill = design.colors.get(style.fill, style.fill) if style.fill is not None else None
    line_color = (
        design.colors.get(style.line_color, style.line_color)
        if style.line_color is not None
        else None
    )
    line_width_pt = (
        parse_length(style.line_width, strict=True) / EMU_PER_POINT
        if style.line_width is not None
        else None
    )

    return ResolvedShapeStyle(fill=fill, line_color=line_color, line_width_pt=line_width_pt)


def _merge_element(layout_element: Element | None, override: Element | None) -> dict[str, Any]:
    """Deep-merge a layout zone's definition with a slide's override for it.

    Both sides are dumped with `exclude_unset=True` so only fields a YAML
    author actually wrote participate -- otherwise every unset field on
    an override (which pydantic fills with `None` defaults) would clobber
    the layout's values via `deep_merge`'s "scalars replace outright"
    rule, defeating the whole point of a partial override (spec section
    7.2).
    """
    base = layout_element.model_dump(exclude_unset=True) if layout_element is not None else {}
    if override is None:
        return base
    return deep_merge(base, override.model_dump(exclude_unset=True))


def _iter_slide_element_pairs(
    slide: Slide, layout: Layout | None
) -> Iterator[tuple[str, Element | None, Element | None]]:
    """Yield `(element_id, layout_element, override)` for every element a
    slide should consider: a named layout's zones (in layout declaration
    order), any dict-keyed slide-level elements the layout doesn't define
    (spec section 19 #4: "add elements"), and any list-keyed elements the
    slide supplies directly.

    Branches on the actual shape of `slide.elements` rather than on
    whether `layout` is `None`: the minimal-deck fixture's `title` slide
    uses `layout: blank` (a named, empty layout) together with list-form
    elements, so "list form only happens under `layout: null`" does not
    hold in practice -- a named layout with no zones and list-form
    elements is just as valid, and a slide could in principle use list
    form to add elements alongside a zoned layout's own zones too.
    """
    overrides_by_id: dict[str, Element] = (
        slide.elements if isinstance(slide.elements, dict) else {}
    )
    extra_elements: list[Element] = (
        slide.elements if isinstance(slide.elements, list) else []
    )

    seen: set[str] = set()
    if layout is not None:
        for element_id, layout_element in layout.elements.items():
            seen.add(element_id)
            yield element_id, layout_element, overrides_by_id.get(element_id)

    for element_id, override in overrides_by_id.items():
        if element_id not in seen:
            yield element_id, None, override

    for position, element in enumerate(extra_elements):
        if element.id is None:
            raise ContentValidationError(
                f"slide {slide.id!r}: element at position {position} in its "
                "element list has no id (spec section 7.7 requires an id "
                "for elements given as a list)"
            )
        if element.id in seen:
            raise ContentValidationError(
                f"slide {slide.id!r}: element id {element.id!r} in its "
                "element list collides with a layout zone of the same name"
            )
        seen.add(element.id)
        yield element.id, None, element


def _has_content(element_type: str, merged: dict[str, Any]) -> bool:
    """Whether a merged element carries enough to render, per type.

    `shape` and `group` have no `value`/`source` of their own -- a shape's
    content is its `shape_kind`, a group's is its `elements` -- so each
    gets its own presence check; every other type falls back to the
    original `value`/`source` rule.
    """
    if element_type == "group":
        return bool(merged.get("elements"))
    if element_type == "shape":
        return merged.get("shape_kind") is not None
    return merged.get("value") is not None or merged.get("source") is not None


def _iter_child_entries(
    children: Any, *, context: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield `(child_id, merged_child_dict)` for a `group` element's
    already-merged `elements` value (dict-keyed or list-keyed, mirroring
    `Slide.elements` -- spec section 7.6). Unlike `_iter_slide_element_pairs`,
    there is no separate layout-zone/override merge here: a group's
    children are whatever `_merge_element` already folded into the
    group's own `elements` key, so each entry is used as-is.
    """
    if isinstance(children, dict):
        yield from children.items()
        return

    seen: set[str] = set()
    for position, child in enumerate(children or []):
        child_id = child.get("id") if isinstance(child, dict) else None
        if not child_id:
            raise ContentValidationError(
                f"{context}: child at position {position} in its element "
                "list has no id (spec section 7.7 requires an id for "
                "elements given as a list)"
            )
        if child_id in seen:
            raise ContentValidationError(f"{context}: duplicate child id {child_id!r}")
        seen.add(child_id)
        yield child_id, child


def _resolve_element(
    slide_id: str,
    element_id: str,
    merged: dict[str, Any],
    design: DesignDocument,
    *,
    strict: bool,
    order: int,
) -> ResolvedElement | None:
    element_type = merged.get("type")
    required = bool(merged.get("required", False))

    if not _has_content(element_type, merged):
        # Covers both an untouched layout zone (`slot`/`footnotes`,
        # spec section 7.5's `content`/`footnotes` example) and any
        # other element type left empty -- either way, an unfilled,
        # non-required element is simply skipped rather than rendered
        # as nothing (spec section 7.7's `required` field is exactly
        # the opt-in for "this must not be empty"). Type validity is
        # checked only once there's actually something to render, same
        # as the original single-pass version of this check -- an empty
        # zone of an unimplemented type is still just an empty zone.
        if required:
            raise ContentValidationError(
                f"slide {slide_id!r}: required element {element_id!r} "
                "has no content"
            )
        return None

    if element_type is None:
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: no element "
            "type resolved for this element"
        )
    if element_type not in SUPPORTED_ELEMENT_TYPES:
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: element type "
            f"{element_type!r} is not implemented yet (see "
            "deckifyr-specification.md section 18)"
        )

    box = merged.get("box")
    if box is None:
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: no box/"
            "geometry resolved for this element"
        )

    style = (
        _resolve_text_style(design, merged.get("style"))
        if element_type in ("text", "markdown")
        else None
    )
    shape_style = (
        _resolve_shape_style(design, merged.get("style")) if element_type == "shape" else None
    )

    children: list[ResolvedElement] = []
    if element_type == "group":
        context = f"slide {slide_id!r}, group {element_id!r}"
        for child_order, (child_id, child_merged) in enumerate(
            _iter_child_entries(merged.get("elements"), context=context)
        ):
            resolved_child = _resolve_element(
                slide_id, child_id, child_merged, design, strict=strict, order=child_order
            )
            if resolved_child is not None:
                children.append(resolved_child)
        children.sort(key=lambda e: (e.z_index, e.order))

    rotation = merged.get("rotation")
    z_index = merged.get("z_index")
    fit = merged.get("fit")
    overflow = merged.get("overflow")
    render_mode = merged.get("render_mode")

    return ResolvedElement(
        id=element_id,
        type=element_type,
        value=merged.get("value"),
        source=merged.get("source"),
        x=parse_length(box["x"], strict=strict),
        y=parse_length(box["y"], strict=strict),
        width=parse_length(box["width"], strict=strict),
        height=parse_length(box["height"], strict=strict),
        rotation=rotation if rotation is not None else design.defaults.rotation,
        z_index=z_index if z_index is not None else 0,
        order=order,
        style=style,
        fit=fit if fit is not None else design.defaults.image_fit,
        overflow=overflow if overflow is not None else design.defaults.overflow,
        render_mode=render_mode if render_mode is not None else "native",
        alt_text=merged.get("alt_text"),
        required=required,
        shape_kind=merged.get("shape_kind"),
        shape_style=shape_style,
        children=children,
    )


def _furniture_layout(
    design: DesignDocument, *, page_number: int, total_pages: int
) -> Layout:
    """Expand `design.yaml`'s `furniture` block (spec section 7.8) into
    reserved, low-`z_index` elements. Furniture is not a new element
    `type` -- these are ordinary `image`/`text` elements, synthesized
    once per slide the same way a layout zone is, so they reuse existing
    merge, override, and composition machinery rather than a parallel
    code path (spec section 7.8's closing note).
    """
    elements: dict[str, Element] = {}

    if design.slide.background_image:
        elements[_FURNITURE_BACKGROUND_ID] = Element(
            type="image",
            source=design.slide.background_image,
            box=Box(
                x="0in", y="0in", width=design.slide.width, height=design.slide.height
            ),
            z_index=_FURNITURE_BACKGROUND_Z_INDEX,
            alt_text=_FURNITURE_BACKGROUND_ALT_TEXT,
        )

    status = design.furniture.status
    if status is not None and status.enabled:
        elements[_FURNITURE_STATUS_ID] = Element(
            type="text",
            value=status.text,
            box=status.box,
            style=status.style,
            z_index=_FURNITURE_OVERLAY_Z_INDEX,
        )

    branding = design.furniture.branding
    if branding is not None:
        elements[_FURNITURE_BRANDING_ID] = Element(
            type="text",
            value=branding.text,
            box=branding.box,
            style=branding.style,
            z_index=_FURNITURE_OVERLAY_Z_INDEX,
        )

    page_number_furniture = design.furniture.page_number
    if page_number_furniture is not None and page_number_furniture.enabled:
        try:
            text = page_number_furniture.format.format(page=page_number, total=total_pages)
        except KeyError as exc:
            raise ContentValidationError(
                "design.yaml furniture.page_number.format "
                f"{page_number_furniture.format!r}: only {{page}} and "
                f"{{total}} placeholders are supported (unknown placeholder "
                f"{exc})"
            ) from exc
        elements[_FURNITURE_PAGE_NUMBER_ID] = Element(
            type="text",
            value=text,
            box=page_number_furniture.box,
            style=page_number_furniture.style,
            z_index=_FURNITURE_OVERLAY_Z_INDEX,
        )

    return Layout(elements=elements)


def expand_slide(
    slide: Slide,
    layout: Layout | None,
    design: DesignDocument,
    *,
    strict: bool,
    page_number: int = 1,
    total_pages: int = 1,
) -> ResolvedSlide:
    furniture_layout = _furniture_layout(
        design, page_number=page_number, total_pages=total_pages
    )
    combined_layout = Layout(
        elements={**furniture_layout.elements, **(layout.elements if layout else {})}
    )

    resolved: list[ResolvedElement] = []

    for order, (element_id, layout_element, override) in enumerate(
        _iter_slide_element_pairs(slide, combined_layout)
    ):
        if override is not None and override.remove:
            continue

        merged = _merge_element(layout_element, override)
        resolved_element = _resolve_element(
            slide.id, element_id, merged, design, strict=strict, order=order
        )
        if resolved_element is not None:
            resolved.append(resolved_element)

    resolved.sort(key=lambda e: (e.z_index, e.order))
    return ResolvedSlide(id=slide.id, elements=resolved)


def expand_presentation(
    presentation: PresentationDocument,
    design: DesignDocument,
    layouts: LayoutsDocument,
    *,
    strict: bool,
) -> list[ResolvedSlide]:
    total_pages = len(presentation.slides)
    return [
        expand_slide(
            slide,
            layouts.layouts[slide.layout] if slide.layout is not None else None,
            design,
            strict=strict,
            page_number=index + 1,
            total_pages=total_pages,
        )
        for index, slide in enumerate(presentation.slides)
    ]
