"""Reusable annotated string types for fields the web editor renders
specially.

Both aliases are plain `str` to pydantic -- validation is unchanged, and
a value is still a `colors:` token / literal hex or a unit-suffixed
length string exactly as before. The only addition is an
`x-deckifyr-widget` annotation in the generated JSON Schema, which the
web editor's schema-driven form (`SchemaForm.tsx`) reads to offer a
color picker with the document's own tokens, or a unit-aware length
input. The `x-` prefix keeps it a vendor annotation that generic JSON
Schema tooling (editor YAML language servers included) ignores, where
an invented standard `format` value could trip a strict validator.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

ColorRef = Annotated[str, Field(json_schema_extra={"x-deckifyr-widget": "color"})]
"""A color: a `design.yaml` `colors:` token name or a literal hex value."""

Length = Annotated[str, Field(json_schema_extra={"x-deckifyr-widget": "length"})]
"""A length with an explicit unit (`in`/`pt`/`cm`/`mm`), e.g. `0.75in`."""
