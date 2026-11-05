"""Structured build warnings (issue #85).

A build warning used to be a bare `str`, so a machine caller (the R facade,
CI, a workspace launcher) could only count them from the CLI -- the text
lived in the optional manifest. `BuildWarning` keeps the message *and* a
stable `code` plus the `slide`/`element` it came from.

It is a `str` subclass on purpose: warnings already flow through resolvers,
five compose functions, the manifest's `warnings` list and `inspect`, all
typed `list[str]`. A subclass is a drop-in everywhere those expect text
(`"LibreOffice" in w`, `json.dumps`, `str.join`) while carrying the
structure, so nothing had to be re-typed and there is no second parallel
list to keep in sync with the first.
"""

from __future__ import annotations

from typing import Any

# Codes are stable identifiers (like `schema.errors.ErrorCode`): callers may
# branch on them, so a message can be reworded without breaking anyone.
W_GENERAL = "W_GENERAL"
W_PREVIEW_SKIPPED = "W_PREVIEW_SKIPPED"
W_FLEXTABLE_RENDERED = "W_FLEXTABLE_RENDERED"
W_MULTI_FIGURE = "W_MULTI_FIGURE"
W_MISSING_SIDECAR = "W_MISSING_SIDECAR"
W_INVALID_SIDECAR = "W_INVALID_SIDECAR"
W_UNITLESS_LENGTH = "W_UNITLESS_LENGTH"


class BuildWarning(str):
    """A warning message that also knows its `code`, `slide` and `element`."""

    code: str
    slide: str | None
    element: str | None

    def __new__(
        cls,
        message: str,
        code: str = W_GENERAL,
        slide: str | None = None,
        element: str | None = None,
    ) -> BuildWarning:
        obj = super().__new__(cls, message)
        obj.code = code
        obj.slide = slide
        obj.element = element
        return obj

    def located(self, slide: str | None, element: str | None) -> BuildWarning:
        """A copy with `slide`/`element` filled in where not already set.

        Fill-only, so a warning raised by a group's child keeps the child's
        own element id when the group tags it again on the way up.
        """
        return BuildWarning(
            str(self),
            self.code,
            self.slide if self.slide is not None else slide,
            self.element if self.element is not None else element,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "slide": self.slide,
            "element": self.element,
        }


def as_build_warning(warning: str) -> BuildWarning:
    """Coerce any plain string (e.g. from a third-party resolver) to a `BuildWarning`."""
    return warning if isinstance(warning, BuildWarning) else BuildWarning(str(warning))


def warnings_payload(warnings: list[str]) -> list[dict[str, Any]]:
    """The `warnings` list of a `--json` result: one dict per warning."""
    return [as_build_warning(w).to_dict() for w in warnings]
