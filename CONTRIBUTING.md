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

`NAMESPACE` is currently hand-written (see its own header comment) since
no roxygen2 toolchain has run in this repo yet. Once you have `roxygen2`
available, regenerate it with:

```bash
Rscript -e 'roxygen2::roxygenise()'
```

and confirm the diff is empty or intentional -- every exported function
already carries a matching `#' @export` roxygen block.

## Before opening a PR

- `uv run --extra dev pytest tests/python -v` passes.
- R tests pass or skip cleanly (see above).
- If you touched `R/run-python.R` or `inst/python/deckifyr/cli.py`'s
  stdout/stderr handling, re-read both files' comments about the
  stdout/stderr handshake between them before changing either side --
  see CLAUDE.md's architecture notes for why it's load-bearing.
