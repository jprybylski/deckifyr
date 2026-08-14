"""Versioned pydantic schemas for design.yaml, layouts.yaml, and
presentation.yaml (spec section 7), plus the small supporting utilities
(unit parsing, deep merge, error codes) they and the CLI share.
"""

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode, SchemaValidationError
from deckifyr.schema.layouts import Element, LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument

__all__ = [
    "DesignDocument",
    "LayoutsDocument",
    "PresentationDocument",
    "Element",
    "DeckifyrError",
    "SchemaValidationError",
    "ErrorCode",
]
