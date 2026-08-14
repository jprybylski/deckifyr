"""Stable, message-independent error codes (spec section 11.1/13).

The CLI's JSON output reports `code`, not just a free-text message, so
callers can branch on failures without parsing prose. Codes are strings,
not an IntEnum: stable across releases matters more than compactness, and
plain strings serialize to JSON without a custom encoder.
"""

from __future__ import annotations


class ErrorCode:
    SCHEMA_VERSION = "E_SCHEMA_VERSION"
    SCHEMA_VALIDATION = "E_SCHEMA_VALIDATION"
    UNIT_PARSE = "E_UNIT_PARSE"
    UNIT_REQUIRED = "E_UNIT_REQUIRED"
    REFERENCE_NOT_FOUND = "E_REFERENCE_NOT_FOUND"
    NOT_IMPLEMENTED = "E_NOT_IMPLEMENTED"
    IO = "E_IO"
    CONTENT_VALIDATION = "E_CONTENT_VALIDATION"


class DeckifyrError(Exception):
    """Base class for errors the CLI reports with a stable `code`."""

    code: str = "E_UNKNOWN"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class SchemaValidationError(DeckifyrError):
    code = ErrorCode.SCHEMA_VALIDATION


class UnitParseError(DeckifyrError):
    code = ErrorCode.UNIT_PARSE


class ContentValidationError(DeckifyrError):
    """Raised when a slide plan references content the compiler can't yet
    resolve or compose: an unsupported element type (spec section 7.7's
    `type` values not yet implemented -- quarto/reportifyr, see
    deckifyr-specification.md section 18), a required element left
    unresolved, or missing required alt text (spec section 13's "Content
    validation" category).
    """

    code = ErrorCode.CONTENT_VALIDATION


class NotImplementedFeatureError(DeckifyrError):
    """Raised by CLI subcommands that are wired up but not yet built.

    Distinct from Python's builtin NotImplementedError so it can carry a
    stable error code through the same CLI error-reporting path as every
    other DeckifyrError, and so `except NotImplementedError` elsewhere in
    the stdlib/dependencies can't accidentally swallow it.
    """

    code = ErrorCode.NOT_IMPLEMENTED
