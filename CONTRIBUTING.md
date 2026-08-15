# Contributing

## Git hooks

```bash
git config core.hooksPath .githooks
```

One-time, per clone. Currently just `.githooks/pre-commit`: a reminder
(not a hard requirement, mirroring `../quartifyr`'s own hook) that warns
when a commit touches a source that feeds `man/figures/demo-deck-*.png`
or the downloadable `man/figures/demo-deck.pptx` -- e.g.
`examples/demo-deck/presentation.yaml` or the PPTX compositor in
`inst/python/deckifyr/pptx/` -- without also touching that asset group.
See the hook script itself for the exact trigger list and the
regeneration recipe. Skip a false positive (a comment or refactor with
identical composed output, say) with `SKIP_DOCS_ASSET_CHECK=1 git commit`
or `git commit --no-verify`. `man/figures/demo-deck-corner-tr-example.png`
is a supplementary asset in that same glob, rendered from a throwaway
`status_indicator: corner-tr` copy of the project rather than
`presentation.yaml`'s own tracked build -- see the hook script's own
comment for why, and `examples/demo-deck/README.md` for how to
regenerate it.

## Python setup

```bash
uv run --extra dev pytest tests/python -v
# single file
uv run --extra dev pytest tests/python/test_units.py -v
```

`uv run` manages its own ephemeral venv from `pyproject.toml` -- no
manual venv activation needed.

## Rebuilding the web frontend

```bash
cd web && npm install && npm run build
```

`web/` (spec section 12) is a Vite/React/TypeScript app; its build
output lands in `inst/python/deckifyr/web/static/` and is committed to
git, the same "generated output ships in the repo" precedent
`man/figures/*.png` already sets (see this file's own git-hooks section
above) -- neither the Python wheel nor an R package install can run a
Node build at install time. If you touch anything under `web/src/`,
rerun the command above and commit the resulting diff under
`inst/python/deckifyr/web/static/` in the same PR. `npm test` (inside
`web/`) runs the frontend's own vitest suite; run it before opening a
PR that touches `web/src/`.

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

and commit the result -- CI's `R-CMD-check.yaml` workflow (`R CMD
check`) fails if they're out of date with `R/*.R`.

**Every new `@export`ed R function must also be added to `_pkgdown.yml`'s
`reference:` index** (or given `@keywords internal` to deliberately drop
it from the reference page) -- `pkgdown::build_site()` hard-errors,
not just warns, on an exported topic missing from that index ("N topics
missing from index"), and `.github/workflows/pages.yml` runs it on
every push to `main` with no dry-run step, so a missed entry breaks the
live docs deploy immediately after merge. Verify locally before
opening a PR:

```bash
R CMD INSTALL --no-multiarch --with-keep.source .
Rscript -e 'pkgdown::build_site(new_process = FALSE, install = FALSE, preview = FALSE)'
```

(the package must actually be installed first, not just
`devtools::load_all()`-ed -- `pkgdown` loads it fresh via `library()` to
build the reference index and run `@examples`.)

### Running a real `R CMD check`/coverage locally

```bash
Rscript -e 'devtools::check()'
Rscript -e 'covr::package_coverage()'
```

Both install a fresh copy of the package into a temp location and run
`tests/testthat.R` against *that* copy, not your checkout -- so
`tests/testthat/test-wiring.R`'s pyro-dependent tests will report as
skipped (`R CMD check`) or show as 0% coverage (`covr`) here even
though they pass for real under `testthat::test_dir("tests/testthat")`
above. That's expected, not a bug to chase: this repo deliberately
doesn't engineer around it (see CLAUDE.md's architecture notes) --
`ci.yml`'s `full-pipeline` job is the actual integration proof, run
directly against the checkout instead.

## Before opening a PR

- `uv run --extra dev pytest tests/python -v` passes.
- R tests pass or skip cleanly (see above).
- `Rscript -e 'roxygen2::roxygenise()'` produces no unexpected diff if
  you touched any `R/*.R` doc comment.
- Any new `@export`ed R function is added to `_pkgdown.yml`'s
  `reference:` index (see above) -- confirm with a local
  `pkgdown::build_site()` run, not just by eyeballing the YAML.
- If you touched `R/run-python.R` or `inst/python/deckifyr/cli.py`'s
  stdout/stderr handling, re-read both files' comments about the
  stdout/stderr handshake between them before changing either side --
  see CLAUDE.md's architecture notes for why it's load-bearing.
