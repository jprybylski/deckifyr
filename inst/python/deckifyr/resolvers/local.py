"""Local file resolver (spec section 9.2).

Resolves an element's `source` to a file inside the project, for sources
that are neither a `{rpfy}:` magic string (reportifyr's resolver, spec
section 9.1 -- not implemented yet) nor a remote URL. Only local,
project-relative files are in scope here; nothing in this resolver
executes code or performs network access (spec section 11.1: "No
implicit network access during a build").
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from deckifyr.resolvers import BuildContext, ResolvedContent
from deckifyr.schema.errors import ContentValidationError


class LocalFileResolver:
    def supports(self, value: str) -> bool:
        if value.startswith("{rpfy}:"):
            return False
        return urlparse(value).scheme == ""

    def resolve(self, value: str, context: BuildContext) -> ResolvedContent:
        project_root = Path(context.project_root).resolve()
        candidate = (project_root / value).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            # Spec section 15's path-traversal warning is framed around
            # hosted/multi-user deployments, but a `../../etc/passwd`-style
            # `source` is just as much a mistake (or worse) in a trusted
            # local project -- reject it rather than silently resolving
            # outside the project.
            raise ContentValidationError(
                f"source {value!r} resolves outside the project root "
                f"{project_root}"
            ) from exc
        if not candidate.is_file():
            raise ContentValidationError(f"source file not found: {candidate}")
        return ResolvedContent(value=candidate)
