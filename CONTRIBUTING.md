# Contributing

## Python setup

```bash
uv run --extra dev pytest tests/python -v
# single file
uv run --extra dev pytest tests/python/test_units.py -v
```

`uv run` manages its own ephemeral venv from `pyproject.toml` -- no
manual venv activation needed.

## R setup

```bash
Rscript -e 'devtools::load_all(".")'          # load the package for interactive use
Rscript -e 'devtools::load_all("."); testthat::test_dir("tests/testthat")'
```

R tests that exercise the real R -> pyro -> Python bridge (as opposed to
just checking function signatures) need `uv` on `PATH` and the `pyro`
package installed; they `skip()` cleanly when either is missing rather
than failing the suite.

`NAMESPACE`/`man/*.Rd` are roxygen2-generated. After changing any `#'`
doc comment or `@export` in `R/*.R`, regenerate both with:

```bash
Rscript -e 'roxygen2::roxygenise()'
```

and commit the result -- CI's `r-check` job (`R CMD check`) fails if
they're out of date with `R/*.R`.

### Running a real `R CMD check`/coverage locally

```bash
Rscript -e 'devtools::check()'
DECKIFYR_DEV_VENV_ROOT="$(pwd)" Rscript -e 'covr::package_coverage()'
```

Both install a fresh copy of the package into a temp location and run
`tests/testthat.R` against *that* copy, not your checkout -- so
`pyro::get_venv_uv_paths()`'s default `here::here()`-based lookup can't
find this checkout's `.venv/` (deliberately excluded from the package by
`.Rbuildignore`) by relative path alone. `DECKIFYR_DEV_VENV_ROOT`
(read by `tests/testthat/test-wiring.R`) works around this -- without
it, every integration test in that file silently skips (`R CMD check`)
or `covr` reports a flat 0% for every `R/*.R` file, in both cases not
because the bridge doesn't work but because the temp copy can't find
`.venv/`. CI's `r-check`/`r-coverage` jobs set this to
`${{ github.workspace }}`; set it to your own checkout's absolute path
locally.

## Before opening a PR

- `uv run --extra dev pytest tests/python -v` passes.
- R tests pass or skip cleanly (see above).
- `Rscript -e 'roxygen2::roxygenise()'` produces no unexpected diff if
  you touched any `R/*.R` doc comment.
- If you touched `R/run-python.R` or `inst/python/deckifyr/cli.py`'s
  stdout/stderr handling, re-read both files' comments about the
  stdout/stderr handshake between them before changing either side --
  see CLAUDE.md's architecture notes for why it's load-bearing.
