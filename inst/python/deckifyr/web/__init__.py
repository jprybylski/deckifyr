"""Optional local-first web application (spec section 12) -- Phase 3.

An authoring/build interface over the CLI/core, not an owner of
presentation logic -- everything it would call already needs to exist
in `deckifyr.schema`/`deckifyr.pptx`/`deckifyr.resolvers` first. Not
implemented yet, and per spec section 20 warning 5, deliberately
deferred until the CLI and schema stabilize. Requires the `web` extra
(`deckifyr[web]`) once it exists; nothing in this package should be
imported by the core CLI.
"""
