"""Optional local-first web application (spec section 12).

An authoring/build interface over the CLI/core, not an owner of
presentation logic -- everything it calls already exists in
`deckifyr.schema`/`deckifyr.pptx`/`deckifyr.resolvers`/`deckifyr.plan`/
`deckifyr.projectio` first (see `web/app.py`'s own module docstring for
the FastAPI backend, and CLAUDE.md's architecture notes for the fuller
design writeup). Requires the `web` extra (`deckifyr[web]`, i.e.
`fastapi`/`uvicorn`) -- this `__init__.py` itself stays import-safe with
no such import at module load, so `import deckifyr` never requires the
extra; only `web/app.py`/`web/jobs.py` (imported lazily from
`cli.py`'s `serve` handler) need it installed. Nothing in this package
is imported by the core CLI outside that one lazy import point.
"""
