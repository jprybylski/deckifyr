"""Pydantic models for `design.yaml` (spec section 7.4).

Slide dimensions, typography, colors, spacing defaults, and named text
styles. Length fields keep their raw unit strings (`"0.75in"`) rather
than pre-converting to EMU: conversion happens once, during merge/plan
resolution, so a `DesignDocument` can still be inspected or re-serialized
as the YAML a user would recognize.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from deckifyr.schema.layouts import Box
from deckifyr.schema.version import check_schema_version


class GradientStop(BaseModel):
    """One color/position pair along a `Gradient`'s path -- mirrors
    `python-pptx`'s own `a:gs` element, spec section 7.4's "token or bare
    literal" convention for `color` included: `color` may name a
    `design.yaml` `colors:` token or a literal hex value, resolved the
    same way `TextStyle.color`/`ShapeStyle.fill` already are.
    """

    model_config = ConfigDict(extra="forbid")

    color: str
    position: float

    @field_validator("position")
    @classmethod
    def _check_position_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"gradient stop position {value!r} must be between 0.0 and 1.0")
        return value


class Gradient(BaseModel):
    """A linear gradient fill, usable anywhere a plain color fill is
    (`SlideSize.background_gradient`, a `ShapeStyle.fill`). `angle`
    follows `python-pptx`'s own `FillFormat.gradient_angle` convention:
    0 is left-to-right, increasing angles rotate clockwise, so 90 (the
    default) is top-to-bottom -- not the CSS `linear-gradient()`
    convention some authors may expect from other tools.
    """

    model_config = ConfigDict(extra="forbid")

    stops: list[GradientStop]
    angle: float = 90

    @field_validator("stops")
    @classmethod
    def _check_min_stops(cls, value: list[GradientStop]) -> list[GradientStop]:
        if len(value) < 2:
            raise ValueError("a gradient needs at least 2 stops")
        return value


class SlideSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: str
    height: str
    background: str = "#FFFFFF"
    safe_area: str = "0in"
    # Optional path/URI, rendered behind all slide content (spec section
    # 7.8's `furniture` design) -- composes with `background` above, which
    # remains the fallback/letterbox color behind a non-covering image.
    background_image: str | None = None
    # Optional linear gradient painted as the slide's own native
    # background fill (spec section 7.4), in front of `background` (its
    # solid-fill fallback is simply unused once this is set) and behind
    # `background_image`/every other element -- the same "paint order"
    # `background_image`'s own docstring above describes.
    background_gradient: Gradient | None = None


class Fonts(BaseModel):
    model_config = ConfigDict(extra="allow")

    body: str
    heading: str
    monospace: str | None = None


class TextStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font: str
    size: str
    bold: bool = False
    italic: bool = False
    color: str
    # Text fill opacity, 0.0 (fully transparent) to 1.0 (fully opaque,
    # the default when unset). `python-pptx` has no public API for run
    # color alpha, so `deckifyr.pptx.compose._apply_text_alpha` sets it
    # directly via lxml when this is set -- the primary use case is a
    # watermark-style `furniture.status` (spec section 7.8) that needs to
    # read consistently on top of arbitrary slide content, not a general
    # replacement for `color`.
    opacity: float | None = None
    # Case transform applied to this style's own rendered text at compose
    # time (`deckifyr.pptx.compose._apply_text_transform`) -- `None` (the
    # default) leaves text exactly as authored. The main use case is a
    # status-indicator style (spec section 7.8) transforming
    # `presentation.yaml`'s own free-text `metadata.status`/`watermark`
    # value ("demo") into the all-caps convention a status/watermark mark
    # conventionally uses ("DEMO") without requiring the author to type
    # it that way themselves.
    text_transform: Literal["none", "uppercase", "lowercase", "capitalize"] | None = None

    @field_validator("opacity")
    @classmethod
    def _check_opacity_range(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError(f"text style opacity {value!r} must be between 0.0 and 1.0")
        return value


class ShapeStyle(BaseModel):
    """A named fill/line style for `shape` elements, alongside `text_styles`
    (spec section 7.4's planned "shape styles" -- see the `design.yaml`
    table in spec section 7.2). Every field is optional and falls back to
    `deckifyr.pptx.compose`'s own default (a thin black outline, no fill)
    when unset, the same "token or bare literal" convention `TextStyle`'s
    `font`/`color` fields use.
    """

    model_config = ConfigDict(extra="forbid")

    fill: str | Gradient | None = None
    line_color: str | None = None
    line_width: str | None = None


class TableStyle(BaseModel):
    """A named fill/border style for `table` elements, alongside
    `shape_styles`. Every field is optional and, when unset, leaves
    `python-pptx`'s own default table-template look (banding, header
    fill, no explicit border) untouched for that aspect -- the same
    "no style token = compositor's own built-in default" convention
    `ShapeStyle` uses. Font/size/bold/italic and the body text color
    remain governed by `text_styles` via a table element's ordinary
    `style` field (unchanged); `TableStyle` only controls the fill/
    border chrome `text_styles` has no vocabulary for. `header_fill`
    overrides the default template's own header band; pair it with
    `header_text_color` when the new fill would leave the template's
    own (unshown, theme-inherited) header text color illegible --
    `deckifyr.pptx.compose` does not infer one from the other.
    """

    model_config = ConfigDict(extra="forbid")

    header_fill: str | None = None
    header_text_color: str | None = None
    body_fill: str | None = None
    # Alternate-row fill for banding; unset means every body row uses
    # `body_fill` (or, if that's also unset, the template's own default).
    band_fill: str | None = None
    border_color: str | None = None
    border_width: str | None = None


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overflow: Literal["error", "shrink", "clip", "continue"] = "error"
    image_fit: Literal["contain", "cover", "stretch", "none"] = "contain"
    rotation: float = 0
    # A `reportifyr`/rpfy-sourced `table` element's `footer_placement:
    # below` box (spec section 9.1's footnote content), placed directly
    # beneath the element's own box.
    footer_height: str = "0.4in"
    # `text_styles` name the footer falls back to when the element itself
    # has no `style` set -- unset means `deckifyr.pptx.compose`'s own
    # small built-in default, same "token or bare literal" convention
    # `TextStyle`'s own fields use.
    footer_style: str | None = None
    # `table_styles` name a `table` element falls back to when it sets no
    # `table_style` of its own -- unset means every table keeps
    # `python-pptx`'s bundled default template look, same "unset here is
    # not the same as unset on the element" precedent `footer_style` sets.
    table_style: str | None = None


class StatusIndicatorStyle(BaseModel):
    """One `status_indicator` placement's own appearance -- a status/
    watermark mark has no content of its own (spec section 7.8's
    `furniture.status` never carries a default word the way, say,
    `branding.text` does): `presentation.yaml`'s own
    `PresentationDocument.watermark` supplies the actual text, any build
    may choose, and this only says where/how it's drawn once chosen.

    `z_index` (unset by default) is what actually chooses which of the
    two conventional "status mark" designs this is: left unset, it keeps
    every other furniture item's own default
    (`_FURNITURE_OVERLAY_Z_INDEX`, well behind ordinary content) -- the
    right choice for a small, simple corner label (a `corner_*` field
    below). Set to a large positive value, it paints on top of every
    ordinary element instead -- a real diagonal watermark (Word/Google
    Docs style) needs to read on top of whatever content it crosses, not
    hide behind it, which is also why that use case should pair
    `rotation` with a low `opacity` on its `style` (`TextStyle.opacity`)
    rather than relying on placement alone.
    """

    model_config = ConfigDict(extra="forbid")

    box: Box
    style: str | None = None
    rotation: float = 0
    z_index: float | None = None


class StatusFurniture(BaseModel):
    """A draft/final/status marker (spec section 7.8) -- off by default
    (every field below is independently optional, and
    `PresentationDocument.status_indicator` defaults to `None`/`"none"`),
    flipped on for a specific build via `presentation.yaml` rather than
    baked into `design.yaml` as always-on.

    Each field is one placement `presentation.yaml`'s own
    `status_indicator` may select -- a full, diagonal, page-spanning
    watermark, or a small label in one of the slide's four corners --
    with its own box/style/rotation/z_index (`StatusIndicatorStyle`).
    `design.yaml` only has to configure the placements a project
    actually intends to use; selecting one `status_indicator` has no
    design-level style for it is a build-time
    `ContentValidationError` (`deckifyr.plan._furniture_layout`), not a
    silent no-op -- spec section 20 warning 7's "do not silently drop
    content" applies here as much as anywhere else. Field names are
    underscored (`corner_tr`, not `corner-tr`) to stay valid Python
    identifiers; `StatusIndicatorMode`'s own literal values (what
    `presentation.yaml` actually types) keep the hyphenated spelling,
    since a YAML string has no such restriction.
    """

    model_config = ConfigDict(extra="forbid")

    watermark: StatusIndicatorStyle | None = None
    corner_tr: StatusIndicatorStyle | None = None
    corner_tl: StatusIndicatorStyle | None = None
    corner_bl: StatusIndicatorStyle | None = None
    corner_br: StatusIndicatorStyle | None = None


class BrandingFurniture(BaseModel):
    """An organization/department label. Unlike `status`/`page_number`
    there's no `enabled` flag -- whether the `furniture.branding` block is
    present at all *is* the toggle, matching spec section 7.8's own
    example YAML. `text` is a literal string: general variable/expression
    substitution (e.g. `{organization}`) is a separate, still-open design
    question (spec section 21) that this does not preempt.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    box: Box
    style: str | None = None


class PageNumberFurniture(BaseModel):
    """A running page number. `format` supports exactly two placeholders,
    `{page}` (1-indexed slide position) and `{total}` (slide count) --
    a closed-form substitution the author cannot hand-write, not a
    general templating mechanism (spec section 21's still-open decision
    about broader variable/expression support is unrelated to this).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    format: str = "{page} / {total}"
    box: Box
    style: str | None = None


class Furniture(BaseModel):
    """`design.yaml`'s `furniture` block (spec section 7.8). Every field
    is optional and unset by default -- a `DesignDocument` with no
    furniture configured expands into nothing extra at all.
    """

    model_config = ConfigDict(extra="forbid")

    status: StatusFurniture | None = None
    branding: BrandingFurniture | None = None
    page_number: PageNumberFurniture | None = None


class DesignDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deckifyr: str
    slide: SlideSize
    fonts: Fonts
    # Named color tokens (spec section 7.4's `colors:` block) -- an open
    # dict rather than fixed fields, since orgs define their own token
    # names beyond the example's text/muted/primary/accent.
    colors: dict[str, str] = {}
    text_styles: dict[str, TextStyle] = {}
    shape_styles: dict[str, ShapeStyle] = {}
    table_styles: dict[str, TableStyle] = {}
    defaults: Defaults = Defaults()
    furniture: Furniture = Furniture()

    _check_version = field_validator("deckifyr")(check_schema_version)
