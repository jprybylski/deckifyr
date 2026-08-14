"""Pydantic models for `layouts.yaml` and the shared element model
(spec sections 7.5 and 7.7).

Layouts are logical Deckifyr constructs that later get expanded onto a
slide as ordinary shapes (spec section 10.2) -- they are not native
PowerPoint layout objects, so nothing here talks to python-pptx.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from deckifyr.schema.version import check_schema_version

ElementType = Literal[
    "text",
    "markdown",
    "quarto",
    "image",
    "table",
    "shape",
    "group",
    "slot",
    "footnotes",
    "reportifyr",
]

FitMode = Literal["contain", "cover", "stretch", "none"]
OverflowMode = Literal["error", "shrink", "clip", "continue"]
RenderMode = Literal["native", "svg", "png", "auto"]


class Box(BaseModel):
    """Explicit geometry: origin top-left, +x right, +y down (spec section 7.3).

    Fields keep their raw unit strings; `deckifyr.schema.units.parse_length`
    converts them to EMUs during plan resolution, not here.
    """

    model_config = ConfigDict(extra="forbid")

    x: str
    y: str
    width: str
    height: str


class Element(BaseModel):
    """One element, as it appears in either a layout or a slide override.

    `id` is optional here because layouts.yaml and presentation.yaml's
    dict-keyed slide forms (spec section 7.6's `elements: {title: ...}`)
    use the mapping key as the id; only the list-keyed freeform form
    (`elements: [{id: ..., ...}]`) sets it inline. Every field besides
    `type` is optional so an override can touch only what it changes,
    per the merge precedence in spec section 7.2.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: ElementType | None = None
    value: Any | None = None
    source: str | None = None
    box: Box | None = None
    rotation: float | None = None
    z_index: int | None = None
    style: str | None = None
    fit: FitMode | None = None
    overflow: OverflowMode | None = None
    render_mode: RenderMode | None = None
    alt_text: str | None = None
    remove: bool = False
    required: bool = False


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elements: dict[str, Element] = {}


class LayoutsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deckifyr: str
    layouts: dict[str, Layout]

    _check_version = field_validator("deckifyr")(check_schema_version)
