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


class ShapeStyle(BaseModel):
    """A named fill/line style for `shape` elements, alongside `text_styles`
    (spec section 7.4's planned "shape styles" -- see the `design.yaml`
    table in spec section 7.2). Every field is optional and falls back to
    `deckifyr.pptx.compose`'s own default (a thin black outline, no fill)
    when unset, the same "token or bare literal" convention `TextStyle`'s
    `font`/`color` fields use.
    """

    model_config = ConfigDict(extra="forbid")

    fill: str | None = None
    line_color: str | None = None
    line_width: str | None = None


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


class StatusFurniture(BaseModel):
    """A draft/final marker (spec section 7.8) -- off by default, flipped
    on for in-progress decks and off again at release, per the spec's own
    example.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    text: str = "DRAFT"
    box: Box
    style: str | None = None


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
    defaults: Defaults = Defaults()
    furniture: Furniture = Furniture()

    _check_version = field_validator("deckifyr")(check_schema_version)
