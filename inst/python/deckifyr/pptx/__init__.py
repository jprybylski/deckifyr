"""PowerPoint compositor (spec section 10).

`deckifyr.pptx.compose` expands a resolved plan (`deckifyr.plan`) into an
in-memory `python-pptx` `Presentation` and a build manifest (spec section
14), for `text`/`markdown`/`image`/`shape`/`group`/`table`/`reportifyr`/
`quarto` elements -- `deckifyr build` (see `deckifyr.cli`'s `build`
subcommand) calls `compose_and_write` after validating and planning a
project. A `quarto` element requires the external `quarto` binary on
`PATH` (spec section 8.1, issue #3); every other element type needs
nothing beyond this package's own Python dependencies.

Per spec section 10.2/section 20 warning 9: low-level OOXML workarounds
must stay isolated behind narrowly tested adapters in here (there is
exactly one, `compose._set_alt_text`) and must never leak into the
public schema in `deckifyr.schema`.
"""

from deckifyr.pptx.compose import BuildResult, compose, compose_and_write

__all__ = ["BuildResult", "compose", "compose_and_write"]
