"""Content resolvers (spec section 9.2).

A resolver turns a slide element's `value`/`source` into concrete
content -- a local file, a `{rpfy}:` reportifyr magic string, a Quarto
fragment, an inline Markdown string, or a CSV/Parquet table.
`LocalFileResolver` (`deckifyr.resolvers.local`), `InlineResolver`
(`deckifyr.resolvers.inline`), `TableResolver`
(`deckifyr.resolvers.table`), `ReportifyrResolver`
(`deckifyr.resolvers.reportifyr`), and `QuartoResolver`
(`deckifyr.resolvers.quarto`) are real -- they cover the `image`,
`text`/`markdown`, `table`, `reportifyr`, and `quarto` element types
`deckifyr.pptx` composes today. Nothing here reuses reportifyr's
own DOCX fill layer (spec section 9.1) -- only its documented `{rpfy}:`
string contract and metadata sidecars; see `deckifyr.resolvers.reportifyr`'s
own module docstring for what was checked before deciding that. Nor does
`QuartoResolver` reuse Quarto's own PPTX writer (spec section 20 warning
2) -- see `deckifyr.resolvers.quarto`'s own module docstring.
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


# Imported after the types above so `deckifyr.resolvers.local`/`.inline`
# (which import BuildContext/ResolvedContent back from this module) see
# them already defined on this partially-initialized module.
from deckifyr.resolvers.inline import InlineResolver  # noqa: E402
from deckifyr.resolvers.local import LocalFileResolver  # noqa: E402
from deckifyr.resolvers.quarto import QuartoArtifact, QuartoResolver  # noqa: E402
from deckifyr.resolvers.reportifyr import (  # noqa: E402
    ReportifyrArtifact,
    ReportifyrResolver,
    TextSegment,
    build_footer_lines,
    load_standard_footnotes,
    split_scripts,
)
from deckifyr.resolvers.table import TableData, TableResolver  # noqa: E402

__all__ = [
    "BuildContext",
    "ResolvedContent",
    "ContentResolver",
    "LocalFileResolver",
    "InlineResolver",
    "TableResolver",
    "TableData",
    "ReportifyrResolver",
    "ReportifyrArtifact",
    "TextSegment",
    "build_footer_lines",
    "load_standard_footnotes",
    "split_scripts",
    "QuartoResolver",
    "QuartoArtifact",
]
