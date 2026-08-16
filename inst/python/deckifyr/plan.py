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

from deckifyr.schema.design import DesignDocument, Gradient
from deckifyr.schema.errors import ContentValidationError
from deckifyr.schema.layouts import Box, Element, Layout, LayoutsDocument
from deckifyr.schema.merge import deep_merge
from deckifyr.schema.presentation import PresentationDocument, Slide
from deckifyr.schema.units import EMU_PER_POINT, parse_length

# Element types this slice's compositor can actually place on a slide.
# Everything else in spec section 7.7's `type` enum is later-phase work
# (deckifyr-specification.md section 18) -- raising a clear error here
# keeps that boundary explicit instead of silently dropping content
# (spec section 20 warning 7).
SUPPORTED_ELEMENT_TYPES = {
    "text",
    "markdown",
    "image",
    "shape",
    "group",
    "table",
    "reportifyr",
    "quarto",
}

# Reserved ids for `design.yaml`'s `furniture` block (spec section 7.8),
# synthesized fresh per slide by `_furniture_layout` below. The
# `__furniture_` prefix keeps these out of the way of author-chosen zone/
# element ids, so the ordinary duplicate-id check in
# `_iter_slide_element_pairs` is a non-issue in practice. Public (no
# leading underscore) because `deckifyr.web.app`'s furniture-editing
# routes (issue #21) need to resolve an incoming element id back to the
# design.yaml field it maps to -- the same "mechanism in its own module"
# split this file's other public helpers already follow.
FURNITURE_BACKGROUND_ID = "__furniture_background"
FURNITURE_STATUS_ID = "__furniture_status"
FURNITURE_BRANDING_ID = "__furniture_branding"
FURNITURE_PAGE_NUMBER_ID = "__furniture_page_number"

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
    opacity: float | None
    text_transform: str | None


@dataclass
class ResolvedGradientStop:
    color: str
    position: float


@dataclass
class ResolvedGradient:
    """A `design.yaml` `Gradient` with its stop colors already resolved to
    literal values, mirroring `ResolvedTextStyle`/`ResolvedShapeStyle`.
    `angle` is passed straight through -- it has no token indirection to
    resolve, unlike `stops[*].color`.
    """

    stops: list[ResolvedGradientStop]
    angle: float


@dataclass
class ResolvedShapeStyle:
    """A `design.yaml` shape style with its `fill`/`line_color` tokens
    already resolved to literal values, mirroring `ResolvedTextStyle`.
    Any field left `None` here means "use `deckifyr.pptx.compose`'s own
    default", not "no style" -- that distinction is only meaningful at
    `design.yaml`'s `ShapeStyle` level. `fill` is a `ResolvedGradient`
    rather than a plain color when the style's own `fill` was a
    `Gradient` (spec section 7.4) -- `deckifyr.pptx.compose` branches on
    which one it got.
    """

    fill: str | ResolvedGradient | None
    line_color: str | None
    line_width_pt: float | None


@dataclass
class ResolvedTableStyle:
    """A `design.yaml` table style with its color/border tokens already
    resolved to literal values, mirroring `ResolvedShapeStyle`. Governs
    only fill/border chrome; a table's typography still comes from
    `style`/`ResolvedTextStyle` as before.
    """

    header_fill: str | None
    header_text_color: str | None
    body_fill: str | None
    band_fill: str | None
    border_color: str | None
    border_width_pt: float | None


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
    footer_placement: str | None = None
    shape_kind: str | None = None
    shape_style: ResolvedShapeStyle | None = None
    table_style: ResolvedTableStyle | None = None
    center: bool = False
    align: str | None = None
    # `group`-only: already-resolved children, sorted by paint order the
    # same way `ResolvedSlide.elements` is.
    children: list["ResolvedElement"] = field(default_factory=list)


@dataclass
class ResolvedSlide:
    id: str
    elements: list[ResolvedElement] = field(default_factory=list)
    # Plain speaker-notes text (spec section 7.7's `Slide.notes`), carried
    # through unresolved -- unlike element `value`/`style`, notes have no
    # design tokens to resolve, so this is a straight pass-through.
    notes: str | None = None


def resolve_text_style(
    design: DesignDocument, style_name: str | None
) -> ResolvedTextStyle | None:
    """Resolve a `design.yaml` `text_styles` name to literal font/size/
    color/bold/italic values. Public (not `_`-prefixed) because
    `deckifyr.pptx.compose` reuses it verbatim to resolve a reportifyr
    footer's style -- one resolver for every field a named style
    carries, so a future field added to `TextStyle`/`ResolvedTextStyle`
    is automatically inherited everywhere a style name is resolved,
    footers included, without a second place to remember to update.
    """
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
        font=font,
        size_pt=size_pt,
        bold=style.bold,
        italic=style.italic,
        color=color,
        opacity=style.opacity,
        text_transform=style.text_transform,
    )


def resolve_gradient(design: DesignDocument, gradient: Gradient) -> ResolvedGradient:
    """Resolve a `design.yaml` `Gradient`'s stop colors to literal values.

    Public (not `_`-prefixed) because `deckifyr.pptx.compose` reuses it
    directly for `design.slide.background_gradient` -- a slide-level
    field `deckifyr.plan` never turns into a `ResolvedElement`/shape
    style, so it has no other resolution point in this module.
    """
    return ResolvedGradient(
        stops=[
            ResolvedGradientStop(
                color=design.colors.get(stop.color, stop.color), position=stop.position
            )
            for stop in gradient.stops
        ],
        angle=gradient.angle,
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

    fill: str | ResolvedGradient | None
    if isinstance(style.fill, Gradient):
        fill = resolve_gradient(design, style.fill)
    elif style.fill is not None:
        fill = design.colors.get(style.fill, style.fill)
    else:
        fill = None
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


def _resolve_table_style(
    design: DesignDocument, style_name: str | None
) -> ResolvedTableStyle | None:
    if style_name is None:
        return None
    style = design.table_styles.get(style_name)
    if style is None:
        raise ContentValidationError(
            f"unknown table_style {style_name!r}: not defined in "
            "design.yaml's table_styles"
        )

    def _color(token: str | None) -> str | None:
        return design.colors.get(token, token) if token is not None else None

    border_width_pt = (
        parse_length(style.border_width, strict=True) / EMU_PER_POINT
        if style.border_width is not None
        else None
    )

    return ResolvedTableStyle(
        header_fill=_color(style.header_fill),
        header_text_color=_color(style.header_text_color),
        body_fill=_color(style.body_fill),
        band_fill=_color(style.band_fill),
        border_color=_color(style.border_color),
        border_width_pt=border_width_pt,
    )


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

    if element_type == "quarto":
        # A `quarto` element's content is its fragment file, not an
        # inline `value` (spec section 8.1's own example: `source:
        # fragments/exposure-interpretation.qmd`) -- reject the wrong
        # field the same way `_has_content` would otherwise silently
        # accept a stray `value` as if it were real content.
        quarto_source = merged.get("source")
        if quarto_source is None:
            raise ContentValidationError(
                f"slide {slide_id!r}, element {element_id!r}: a 'quarto' "
                "element requires a 'source' (a .qmd path, spec section "
                "8.1), not an inline 'value'"
            )
        if not str(quarto_source).endswith(".qmd"):
            raise ContentValidationError(
                f"slide {slide_id!r}, element {element_id!r}: a 'quarto' "
                f"element's source must be a .qmd file, got {quarto_source!r}"
            )

    box = merged.get("box")
    if box is None:
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: no box/"
            "geometry resolved for this element"
        )

    style = (
        resolve_text_style(design, merged.get("style"))
        if element_type in ("text", "markdown", "table", "quarto")
        else None
    )
    shape_style = (
        _resolve_shape_style(design, merged.get("style")) if element_type == "shape" else None
    )

    table_style_name = merged.get("table_style")
    if table_style_name is not None and element_type != "table":
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: table_style is "
            "only valid on a 'table' element"
        )
    if element_type == "table" and table_style_name is None:
        table_style_name = design.defaults.table_style
    table_style = (
        _resolve_table_style(design, table_style_name) if element_type == "table" else None
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

    # `footer_placement` (spec section 9.1's reportifyr footnote content)
    # is only meaningful on a `reportifyr` element (its magic string is
    # its `value`, per spec section 7.6's own example) or a `table`
    # element whose `source` is itself a `{rpfy}:` magic string --
    # rejected elsewhere rather than silently ignored, same as any other
    # field that doesn't apply to a given element type.
    source = merged.get("source")
    is_rpfy_table = element_type == "table" and isinstance(source, str) and source.startswith("{rpfy}:")
    footer_applicable = element_type == "reportifyr" or is_rpfy_table
    footer_placement = merged.get("footer_placement")
    if footer_placement is not None and not footer_applicable:
        raise ContentValidationError(
            f"slide {slide_id!r}, element {element_id!r}: footer_placement is "
            "only valid on a 'reportifyr' element or a 'table' element whose "
            "source is a {rpfy}: magic string"
        )
    if footer_applicable and footer_placement is None:
        footer_placement = "below"

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
        # Every other element type always composes natively, so its
        # `render_mode` field is manifest bookkeeping only -- `"native"`
        # is a safe, meaningless-elsewhere default. A `quarto` element
        # actually branches on this value (spec section 8's render-mode
        # table), so its unset default is `"auto"` -- the "convenient
        # defaults by content type" mode, not a forced native/text
        # rendering that would mangle an equation-heavy fragment.
        render_mode=(
            render_mode
            if render_mode is not None
            else ("auto" if element_type == "quarto" else "native")
        ),
        alt_text=merged.get("alt_text"),
        required=required,
        footer_placement=footer_placement,
        shape_kind=merged.get("shape_kind"),
        shape_style=shape_style,
        table_style=table_style,
        center=bool(merged.get("center", False)),
        align=merged.get("align"),
        children=children,
    )


# Maps `PresentationDocument.status_indicator`'s hyphenated literal
# values to `StatusFurniture`'s own underscored field names (spec
# section 7.8's `StatusFurniture` docstring explains why the two spellings
# differ). `"none"`/`None` are deliberately absent -- both mean "no status
# indicator at all" and are handled before this mapping is consulted.
# Public alongside the `FURNITURE_*_ID` constants above -- `deckifyr.web
# .app`'s furniture routes need the same mapping to resolve which
# `design.yaml` `furniture.status.*` field a `status_indicator` selection
# targets.
STATUS_INDICATOR_FIELDS = {
    "watermark": "watermark",
    "corner-tr": "corner_tr",
    "corner-tl": "corner_tl",
    "corner-bl": "corner_bl",
    "corner-br": "corner_br",
}

# A corner placement's horizontal `Element.align` (issue #13): the two
# right-edge corners push their text to the right end of their own box,
# the two left-edge corners to the left end -- so once a `design.yaml`
# author angles the box with `rotation` to hug that edge (its own choice,
# not something this module imposes; see `StatusIndicatorStyle.rotation`'s
# own docstring), the text lands snug against the actual corner rather
# than centered along the strip's full length. `watermark` (and anything
# else not listed here) keeps `align=None`, i.e. `center=True`'s own
# existing full-centering behavior, unchanged.
_STATUS_CORNER_ALIGN = {
    "corner_tr": "right",
    "corner_br": "right",
    "corner_tl": "left",
    "corner_bl": "left",
}


def _furniture_layout(
    design: DesignDocument,
    *,
    page_number: int,
    total_pages: int,
    status_indicator: str | None = None,
    watermark_text: str | None = None,
    lenient: bool = False,
) -> Layout:
    """Expand `design.yaml`'s `furniture` block (spec section 7.8) into
    reserved, low-`z_index` elements. Furniture is not a new element
    `type` -- these are ordinary `image`/`text` elements, synthesized
    once per slide the same way a layout zone is, so they reuse existing
    merge, override, and composition machinery rather than a parallel
    code path (spec section 7.8's closing note).

    `status_indicator`/`watermark_text` are `presentation.yaml`'s own
    `PresentationDocument.status_indicator`/`.watermark` (threaded down
    via `expand_slide`/`expand_presentation`): `status_indicator` picks
    *which* of `design.yaml`'s `furniture.status` placements to use
    (`None`/`"none"` means none at all), `watermark_text` is the actual
    word to show.

    `lenient` (default `False`, unchanged strict behavior for every
    existing caller -- `deckifyr build`/`validate`/`GET /api/plan` must
    never silently drop configured content, spec section 20 warning 7)
    is a real-slide-vs-furniture-editor distinction, not a relaxation of
    that rule: `deckifyr.web.app`'s `GET /api/furniture` route (issue
    #21) is the one place a `status_indicator` selection with no
    matching `furniture.status` style configured yet -- or a
    `page_number.format` with a bad placeholder -- is an *expected,
    mid-fix* state, not an error to surface. With `lenient=True`, either
    condition just omits that one element from the returned `Layout`
    instead of raising, so the furniture pseudo-slide (and its
    `FurnitureControls` "Add" action, the actual fix) stays reachable
    rather than 500ing the one screen that could fix the problem.
    """
    elements: dict[str, Element] = {}

    if design.slide.background_image:
        elements[FURNITURE_BACKGROUND_ID] = Element(
            type="image",
            source=design.slide.background_image,
            box=Box(
                x="0in", y="0in", width=design.slide.width, height=design.slide.height
            ),
            z_index=_FURNITURE_BACKGROUND_Z_INDEX,
            alt_text=_FURNITURE_BACKGROUND_ALT_TEXT,
        )

    if status_indicator is not None and status_indicator != "none":
        field_name = STATUS_INDICATOR_FIELDS[status_indicator]
        # `design.furniture.status` (the whole `StatusFurniture` block,
        # not just one placement) is itself optional -- a project that
        # never configured any status placement at all has it `None`,
        # not an all-`None`-fields object; `getattr` on `None` crashes
        # rather than reporting "not configured" the same way a single
        # missing field does. A real, previously-latent bug (not
        # introduced by `lenient`): the unguarded `getattr` below raised
        # `AttributeError` instead of the intended `ContentValidationError`
        # in this case, in strict mode too -- caught by a lenient-mode
        # regression test against minimal-deck, which has no
        # `furniture.status` block at all.
        status_furniture = design.furniture.status
        indicator_style = (
            getattr(status_furniture, field_name) if status_furniture is not None else None
        )
        if indicator_style is None and not lenient:
            raise ContentValidationError(
                f"presentation.yaml sets status_indicator: {status_indicator!r}, "
                f"but design.yaml's furniture.status has no {field_name!r} "
                "configured"
            )
        # A full-page watermark with no text is rejected at schema
        # validation (`PresentationDocument`'s own model validator); a
        # small corner placement with no text is just empty content --
        # skipped like any other unfilled, non-required element, not an
        # error.
        if indicator_style is not None and watermark_text is not None:
            elements[FURNITURE_STATUS_ID] = Element(
                type="text",
                value=watermark_text,
                box=indicator_style.box,
                style=indicator_style.style,
                rotation=indicator_style.rotation,
                center=True,
                align=_STATUS_CORNER_ALIGN.get(field_name),
                z_index=(
                    indicator_style.z_index
                    if indicator_style.z_index is not None
                    else _FURNITURE_OVERLAY_Z_INDEX
                ),
            )

    branding = design.furniture.branding
    if branding is not None:
        elements[FURNITURE_BRANDING_ID] = Element(
            type="text",
            value=branding.text,
            box=branding.box,
            style=branding.style,
            z_index=_FURNITURE_OVERLAY_Z_INDEX,
        )

    page_number_furniture = design.furniture.page_number
    if page_number_furniture is not None and page_number_furniture.enabled:
        try:
            text: str | None = page_number_furniture.format.format(
                page=page_number, total=total_pages
            )
        except KeyError as exc:
            if not lenient:
                raise ContentValidationError(
                    "design.yaml furniture.page_number.format "
                    f"{page_number_furniture.format!r}: only {{page}} and "
                    f"{{total}} placeholders are supported (unknown placeholder "
                    f"{exc})"
                ) from exc
            text = None
    else:
        text = None
    if text is not None:
        elements[FURNITURE_PAGE_NUMBER_ID] = Element(
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
    status_indicator: str | None = None,
    watermark_text: str | None = None,
    furniture_lenient: bool = False,
) -> ResolvedSlide:
    furniture_layout = _furniture_layout(
        design,
        page_number=page_number,
        total_pages=total_pages,
        status_indicator=status_indicator,
        watermark_text=watermark_text,
        lenient=furniture_lenient,
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
    return ResolvedSlide(id=slide.id, elements=resolved, notes=slide.notes)


def resolve_watermark_text(presentation: PresentationDocument) -> str | None:
    """The status/watermark placement's actual text (spec section 7.8).

    `presentation.watermark` is an explicit override; unset (the usual
    case, per this field's own docstring), the status indicator's text
    falls back to `metadata.status` -- the same free-text field authors
    already set ("draft", "demo", "final", ...) for descriptive
    purposes, so a status/watermark mark doesn't require typing the
    same word twice. `TextStyle.text_transform` (spec section 7.4),
    not this fallback, is what turns "demo" into "DEMO" -- this only
    decides which string gets used at all. Public (not `_`-prefixed)
    because `deckifyr.web.app`'s `GET /api/furniture` route needs the
    same fallback outside of a full `expand_presentation` call.
    """
    return (
        presentation.watermark
        if presentation.watermark is not None
        else presentation.metadata.status
    )


def expand_presentation(
    presentation: PresentationDocument,
    design: DesignDocument,
    layouts: LayoutsDocument,
    *,
    strict: bool,
) -> list[ResolvedSlide]:
    total_pages = len(presentation.slides)
    watermark_text = resolve_watermark_text(presentation)
    return [
        expand_slide(
            slide,
            layouts.layouts[slide.layout] if slide.layout is not None else None,
            design,
            strict=strict,
            page_number=index + 1,
            total_pages=total_pages,
            status_indicator=presentation.status_indicator,
            watermark_text=watermark_text,
        )
        for index, slide in enumerate(presentation.slides)
    ]
