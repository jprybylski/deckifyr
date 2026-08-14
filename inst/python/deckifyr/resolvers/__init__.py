"""Content resolvers (spec section 9.2).

A resolver turns a slide element's `value`/`source` into concrete
content -- a local file, a `{rpfy}:` reportifyr magic string, a Quarto
fragment, an inline Markdown string, or a CSV/Parquet table. Only the
`ContentResolver` protocol is defined so far; concrete resolvers
(local file, reportifyr, Quarto, Markdown, table, image -- spec section
9.2's initial list) are Phase 1/2 work and are not implemented yet.
Nothing here should reuse reportifyr's own DOCX fill layer (spec
section 9.1) -- only its documented `{rpfy}:` string contract and
metadata sidecars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class BuildContext:
    """Placeholder for the resolution-time context a resolver needs
    (project root, allowed input roots, reportifyr metadata index, ...).
    Fields will be filled in alongside the first concrete resolver.
    """

    project_root: str


@dataclass
class ResolvedContent:
    """Placeholder for a resolver's output (resolved path/bytes, source
    metadata, provenance) -- shape is not finalized yet.
    """

    value: Any


class ContentResolver(Protocol):
    def supports(self, value: str) -> bool: ...

    def resolve(self, value: str, context: BuildContext) -> ResolvedContent: ...
