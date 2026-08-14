# Fixtures

Empty on purpose. Both `tests/python/` and `tests/testthat/` reuse
`inst/examples/minimal-deck/` as their shared fixture rather than
duplicating YAML here — see `tests/python/conftest.py`'s
`minimal_deck_dir` fixture and `tests/testthat/test-wiring.R`.

Add fixtures here only for cases the bundled example project
deliberately doesn't cover (e.g. intentionally invalid YAML for negative
tests, or larger reportifyr/Quarto compatibility corpora once those
resolvers exist — spec section 17's "Contract tests").
