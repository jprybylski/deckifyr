"""Quarto integration and render-mode logic (spec section 8) -- Phase 2.

Owns executing `.qmd` fragments and choosing/recording a render mode
(`native`/`svg`/`png`/`auto`) per element. Not implemented yet: nothing
in this package should be imported by working code until Phase 2 starts.

Warning carried forward from the spec: Quarto execution runs arbitrary
project code and must never run inside an unisolated multi-user web
request process (spec section 8, section 15).
"""
