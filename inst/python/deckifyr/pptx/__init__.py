"""PowerPoint compositor (spec section 10) -- Phase 1.

Owns loading a reference .pptx, expanding logical layouts into slide
shapes, and placing content with python-pptx using normalized EMU
geometry. Not implemented yet: `deckifyr build` currently stops before
reaching this package (see `deckifyr.cli`'s `build` subcommand) and
raises `NotImplementedFeatureError` instead of writing a file.

Per spec section 10.2/section 20 warning 9: low-level OOXML workarounds
must stay isolated behind narrowly tested adapters in here and must
never leak into the public schema in `deckifyr.schema`.
"""
