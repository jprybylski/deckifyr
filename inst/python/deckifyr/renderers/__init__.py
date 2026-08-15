"""Quarto integration and render-mode logic (spec section 8) -- Phase 2.

`deckifyr.renderers.quarto` is real (spec section 8.1, issue #3):
executing a `type: quarto` element's `.qmd` fragment (complexity-limited
to a single fragment, execution-timeout- and output-size-bounded) and
turning it into either normalized text (`render_mode: native`) or a
rasterized image (`svg`/`png`) via Quarto's bundled Typst toolchain. See
that module's own docstring for the render-mode tradeoffs and why Typst
rather than a LaTeX-dependent PDF path -- and why `svg`, though real at
this level, never reaches `deckifyr.pptx.compose` (`python-pptx` cannot
embed one at all). `deckifyr.resolvers.quarto` (spec section 9.2's
"Quarto fragment resolver") is the `ContentResolver` that wraps it for
`deckifyr.pptx.compose` the same way `ReportifyrResolver` wraps
reportifyr magic-string resolution.

Warning carried forward from the spec: Quarto execution runs arbitrary
project code and must never run inside an unisolated multi-user web
request process (spec section 8, section 15).
"""
