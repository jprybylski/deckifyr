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
from deckifyr.schema.layouts import Element, Layout, LayoutsDocument
from deckifyr.schema.merge import deep_merge
from deckifyr.schema.presentation import PresentationDocument, Slide
from deckifyr.schema.units import EMU_PER_POINT, parse_length

# Element types this slice's compositor can actually place on a slide.
# Everything else in spec section 7.7's `type` enum (table, shape, group,
# quarto, reportifyr) is later-phase work (deckifyr-specification.md
# section 18) -- raising a clear error here keeps that boundary explicit
# instead of silently dropping content (spec section 20 warning 7).
SUPPORTED_ELEMENT_TYPES = {"text", "markdown", "image"}


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


def expand_slide(
    slide: Slide,
    layout: Layout | None,
    design: DesignDocument,
    *,
    strict: bool,
) -> ResolvedSlide:
    resolved: list[ResolvedElement] = []

    for order, (element_id, layout_element, override) in enumerate(
        _iter_slide_element_pairs(slide, layout)
    ):
        if override is not None and override.remove:
            continue

        merged = _merge_element(layout_element, override)
        element_type = merged.get("type")
        value = merged.get("value")
        source = merged.get("source")
        required = bool(merged.get("required", False))
        has_content = value is not None or source is not None

        if not has_content:
            # Covers both an untouched layout zone (`slot`/`footnotes`,
            # spec section 7.5's `content`/`footnotes` example) and any
            # other element type left empty -- either way, an unfilled,
            # non-required element is simply skipped rather than rendered
            # as nothing (spec section 7.7's `required` field is exactly
            # the opt-in for "this must not be empty").
            if required:
                raise ContentValidationError(
                    f"slide {slide.id!r}: required element {element_id!r} "
                    "has no value/source"
                )
            continue

        if element_type is None:
            raise ContentValidationError(
                f"slide {slide.id!r}, element {element_id!r}: no element "
                "type resolved for this element"
            )
        if element_type not in SUPPORTED_ELEMENT_TYPES:
            raise ContentValidationError(
                f"slide {slide.id!r}, element {element_id!r}: element type "
                f"{element_type!r} is not implemented yet (see "
                "deckifyr-specification.md section 18)"
            )

        box = merged.get("box")
        if box is None:
            raise ContentValidationError(
                f"slide {slide.id!r}, element {element_id!r}: no box/"
                "geometry resolved for this element"
            )

        style = _resolve_text_style(design, merged.get("style"))

        rotation = merged.get("rotation")
        z_index = merged.get("z_index")
        fit = merged.get("fit")
        overflow = merged.get("overflow")
        render_mode = merged.get("render_mode")

        resolved.append(
            ResolvedElement(
                id=element_id,
                type=element_type,
                value=value,
                source=source,
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
            )
        )

    resolved.sort(key=lambda e: (e.z_index, e.order))
    return ResolvedSlide(id=slide.id, elements=resolved)


def expand_presentation(
    presentation: PresentationDocument,
    design: DesignDocument,
    layouts: LayoutsDocument,
    *,
    strict: bool,
) -> list[ResolvedSlide]:
    return [
        expand_slide(
            slide,
            layouts.layouts[slide.layout] if slide.layout is not None else None,
            design,
            strict=strict,
        )
        for slide in presentation.slides
    ]
