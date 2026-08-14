"""Inline value resolver (spec section 9.2).

Passes an element's literal `value` straight through for `text`/
`markdown` elements -- the trivial resolver every content-referencing
resolver (reportifyr magic strings, Quarto fragments, tables) will
eventually sit alongside.
"""

from __future__ import annotations

from deckifyr.resolvers import BuildContext, ResolvedContent


class InlineResolver:
    def supports(self, value: str) -> bool:
        return True

    def resolve(self, value: str, context: BuildContext) -> ResolvedContent:
        return ResolvedContent(value=value)
