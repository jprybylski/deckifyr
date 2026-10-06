"""Guards the schema metadata the web editor's form reads.

`SchemaForm.tsx` shows each property's own `description` as a hint and
reads the `x-deckifyr-widget` annotation (`deckifyr.schema.fields`) to
pick a color picker or a unit-aware length input. A new field without a
description would silently render with no hint, so this fails instead.
"""

from __future__ import annotations

import pytest

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.fields import ColorRef, Length
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument

MODELS = [DesignDocument, LayoutsDocument, PresentationDocument]


def _properties(schema: dict):
    for owner, node in [("<root>", schema), *schema.get("$defs", {}).items()]:
        for name, prop in node.get("properties", {}).items():
            yield owner, name, prop


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_property_has_a_description(model):
    missing = [
        f"{owner}.{name}"
        for owner, name, prop in _properties(model.model_json_schema())
        if not prop.get("description")
    ]
    assert not missing, f"properties without a Field(description=...): {missing}"


def test_widget_aliases_are_plain_strings_with_a_vendor_annotation():
    # Validation is unchanged: both are ordinary `str` to pydantic.
    assert ColorRef.__origin__ is str
    assert Length.__origin__ is str
    schema = DesignDocument.model_json_schema()
    widgets = {
        (owner, name): prop.get("x-deckifyr-widget")
        for owner, name, prop in _properties(schema)
        if "x-deckifyr-widget" in prop
    }
    assert widgets[("TextStyle", "color")] == "color"
    assert widgets[("TextStyle", "size")] == "length"
    assert widgets[("SlideSize", "width")] == "length"
    assert widgets[("Box", "x")] == "length"


def test_colors_entries_keep_their_string_or_derivation_union():
    colors = DesignDocument.model_json_schema()["properties"]["colors"]
    branches = colors["additionalProperties"]["anyOf"]
    assert {"type": "string", "x-deckifyr-widget": "color"} in branches
    assert any(b.get("$ref", "").endswith("ColorDerivation") for b in branches)


def test_a_document_still_validates_with_annotated_fields():
    doc = DesignDocument.model_validate(
        {
            "deckifyr": "0.1",
            "slide": {"width": "13.333in", "height": "7.5in"},
            "fonts": {"body": "Arial", "heading": "Arial"},
            "colors": {"primary": "#2457A6", "tint": {"base": "primary", "lighten": 0.2}},
        }
    )
    assert doc.colors["primary"] == "#2457A6"
