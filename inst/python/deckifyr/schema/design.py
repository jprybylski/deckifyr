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

from deckifyr.schema.version import check_schema_version


class SlideSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: str
    height: str
    background: str = "#FFFFFF"
    safe_area: str = "0in"


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


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overflow: Literal["error", "shrink", "clip", "continue"] = "error"
    image_fit: Literal["contain", "cover", "stretch", "none"] = "contain"
    rotation: float = 0


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
    defaults: Defaults = Defaults()

    _check_version = field_validator("deckifyr")(check_schema_version)
