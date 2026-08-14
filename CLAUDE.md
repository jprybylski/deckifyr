# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

deckifyr is a declarative, code-first presentation compiler: it generates
`.pptx` decks from version-controlled YAML (design tokens, logical
layouts, slide content -- three separate, versioned schemas) instead of
a hand-clicked PowerPoint template. It's a sibling project to
[`../quartifyr`](../quartifyr) in the same `fyr` ecosystem, inheriting
its reproducible, YAML-driven philosophy while targeting slides instead
of Word documents, and it's meant to support
[`reportifyr`](https://github.com/A2-ai/reportifyr) artifacts
(`{rpfy}:` magic strings) the same way quartifyr's shells do -- but as
its own independent repository, release cycle, and dependency graph,
not a subsystem bolted onto quartifyr.

**`deckifyr-specification.md`** at the repo root is the authoritative
design document (architecture, full schema reference, compilation
model, Reportifyr/Quarto integration, security model, phased delivery
plan). Everything below assumes you've skimmed it; this file covers
what's actually built versus still spec, and the non-obvious things
learned while building the scaffold.

### Current status: early scaffold, not the compiler yet

| Piece | Status |
| --- | --- |
| `deckifyr.schema.units` (length parsing, spec §7.3) | Real, tested |
| `deckifyr.schema.merge` (deep-merge precedence, spec §7.2) | Real, tested |
| `deckifyr.schema.{design,layouts,presentation}` (pydantic models, spec §7.4-7.7) | Real, tested |
| `deckifyr.plan` (Pass 1: plan and shell expansion, spec §6) | Real, tested -- `text`/`markdown`/`image` elements only |
| CLI `init`/`validate`/`build`/`schema` (spec §11.1) | Real, tested |
| CLI `preview`/`inspect`/`serve` | Argument parsing is real; each raises `NotImplementedFeatureError` (exit code 4) |
| R facade (`R/*.R`) | Real, tested against a live pyro install |
| `deckifyr.pptx` (PowerPoint compositor, spec §10) | Real, tested for `text`/`markdown`/`image` elements; `table`/`shape`/`group`/`quarto`/`reportifyr` raise a clear `ContentValidationError` (`deckifyr.plan` rejects them before composition) -- Phase 1 |
| `deckifyr.resolvers` concrete resolvers (spec §9.2) | `LocalFileResolver` and `InlineResolver` are real; reportifyr/Quarto/table resolvers are not implemented -- Phase 2 |
| `deckifyr.renderers` (Quarto integration, spec §8) | Not started -- Phase 2 |
| `deckifyr.web` (spec §12) | Not started -- Phase 3 |

Concretely: `deckifyr validate presentation.yaml` does real schema and
geometry validation today. `deckifyr build presentation.yaml` validates
the same way, then plans and composes a real `.pptx` + manifest for
projects that only use `text`/`markdown`/`image` elements -- a project
using `table`/`shape`/`group`/`quarto`/`reportifyr` elements still fails
with a clear "not implemented" error (`E_CONTENT_VALIDATION`) rather
than silently dropping that content. Document furniture (§7.8) isn't
composed at all yet (still gated behind issue #1). Don't assume any
command beyond `init`/`validate`/`build`/`schema` does real work without
checking `inst/python/deckifyr/cli.py` first.

## Components

| Path | What it is | Language |
| --- | --- | --- |
| `R/` | Thin facade (`deck_validate()`, `deck_build()`, `initialize_deck_project()`, ...) delegating to the bundled Python CLI via pyro. `R/run-python.R` is the single bridge point every other `R/*.R` file calls through. | R |
| `inst/python/deckifyr/` | The canonical engine. Bundled unmodified into the R package (`inst/python`) and also the source directory for the standalone Python wheel (spec §5.3) -- never fork this tree for one facade or the other. | Python |
| `inst/examples/minimal-deck/` | A minimal valid `design.yaml`/`layouts.yaml`/`presentation.yaml` trio. Used by `deckifyr init` as its template, and as the shared test fixture for both `tests/python/` and `tests/testthat/` -- don't duplicate its content elsewhere. Ships inside the R package/Python wheel (it's under `inst/`). | YAML |
| `examples/demo-deck/` | A richer, repo-only demo (in the spirit of quartifyr's `examples/demo-report`) -- a three-slide deck using a real `reportifyr`-produced figure copied from quartifyr's `examples/demo-report`, a multi-zone layout, rotation, and `z_index`. Not bundled into the package (outside `inst/`); see its own README.md for what it demonstrates and why it doesn't use `{rpfy}:` yet. | YAML |
| `tests/python/` | pytest, unit-level: units, merge, schema loading, CLI exit codes, plan expansion, PPTX composition -- plus `test_demo_deck.py`, an end-to-end build of `examples/demo-deck/`. | Python |
| `tests/testthat/` | R tests, including `test-wiring.R`, the only test that exercises the real R -> pyro -> Python round trip end-to-end (not just function signatures). Skips cleanly without `uv`/`pyro`. | R |

## Commands

### Python

```bash
uv run --extra dev pytest tests/python -v      # full suite
uv run deckifyr validate inst/examples/minimal-deck/presentation.yaml
uv run deckifyr --json validate ...             # structured output
uv run deckifyr schema presentation             # dump a document type's JSON Schema
uv run deckifyr init some-dir                   # scaffold from the bundled example
```

### R

```r
devtools::load_all(".")
testthat::test_dir("tests/testthat")
deck_validate("inst/examples/minimal-deck/presentation.yaml")
```

`NAMESPACE` and `man/*.Rd` are roxygen2-generated (`Rscript -e
'roxygen2::roxygenise()'`) -- see `CONTRIBUTING.md`. CI's `r-check` job
runs a real `R CMD check` (`r-lib/actions/check-r-package`), which fails
if either is stale relative to `R/*.R`'s `#'` doc comments.

## Architecture notes that span files

**"One engine, two facades" is a hard invariant, not a starting
preference.** Schema validation, merging, geometry, and (eventually)
PPTX composition live only in `inst/python/deckifyr/`. `R/run-python.R`
is the *only* place R talks to Python; every other `R/*.R` file calls
`.run_deckifyr_cli()` rather than reimplementing any part of the
contract. If you're tempted to validate a YAML field in R "just to give
a faster error," don't -- that's exactly the drift spec §20's warning 1
calls out ("Do not maintain independent R and Python presentation
engines. They will diverge.").

**`pyro::run_python_script()` discards stdout/stderr on any non-zero
exit -- confirmed against a real pyro install, not just inferred from
docs.** It wraps `processx::run(..., error_on_status = TRUE)` in a
`tryCatch` that, on failure, throws a bare `"<script_name> failed."`
with no access to what the subprocess actually printed. Since
`deckifyr`'s CLI legitimately exits non-zero for ordinary validation/
not-implemented errors (spec §11.1 requires this), that would silently
swallow every real diagnostic the Python side produces. The fix, live in
`R/run-python.R` and `inst/python/deckifyr/cli.py`'s `main()`, is a
two-sided handshake:
  1. `cli.py` writes its structured JSON error payload to **stderr**
     (not stdout) whenever it's about to exit non-zero; stdout is
     reserved for the success path.
  2. `run-python.R` passes its own `stderr_callback` to
     `run_python_script()`. processx invokes that callback per output
     chunk *while the process is still running*, before the exit-status
     check fires -- so the callback has already captured the JSON error
     by the time pyro's wrapper throws its generic message. The R side
     catches that generic error, re-parses its own captured stderr as
     JSON, and raises the real `code`/`message` instead.

  Don't change one side of this without the other -- e.g. moving the
  error JSON back to stdout in `cli.py` silently breaks R's error
  reporting again (the CLI itself would look fine; only
  `deck_validate()`/`deck_build()`'s error messages would go back to a
  useless generic string).

**A bare `{ ... }` block passed as `tryCatch()`'s `expr` does not get
its own environment -- a real bug this repo hit, not a hypothetical.**
An earlier version of `.run_deckifyr_cli()` declared
`raw_stdout <- NULL` in the function's own frame, then tried to set it
from inside the `tryCatch(expr = { ... }, ...)` block with
`raw_stdout <<- result$stdout`. Because the block shares the calling
frame (braces aren't a scope boundary the way a `function()` body is),
`<<-` skipped right past that local binding and wrote to a *further*
enclosing environment instead, leaving the local `raw_stdout` `NULL`
forever -- every successful call silently reported "did not return
valid JSON" with empty stdout. The fix: have the `tryCatch` expression
*return* the value (or the caught `error` condition) and branch on that
returned object afterward, rather than mutating an outer variable from
inside the expression. `capture_stderr()`'s own `stderr_lines <<- ...`
a few lines away is fine by contrast -- it's inside an actual
`function(chunk, proc) { ... }`, which is a real closure, so `<<-`
there correctly reaches the enclosing frame where `stderr_lines` lives.
If you're about to write `<<-` inside a `tryCatch`/`withCallingHandlers`
block, ask whether that block is a real function or just braces.

**Unit model: YAML always spells units out; EMU only internally (spec
§7.3).** `deckifyr.schema.units.parse_length()` is the only place that
conversion happens, and only there does "unitless" get a strict/
permissive distinction -- pydantic models in `schema/design.py`/
`layouts.py`/`presentation.py` keep box/length fields as raw strings on
purpose, so a validated document can still be inspected or
re-serialized as the YAML a user recognizes. Don't pre-convert to EMU
inside a pydantic model.

**Merge precedence (spec §7.2) is one pairwise operation
(`deckifyr.schema.merge.deep_merge`) folded over a precedence-ordered
layer list, not a bespoke merge per document type.** Dicts merge
recursively; scalars and lists replace outright. If a future element
type needs additive list behavior, that's a schema-level opt-in on that
field, not a change to `deep_merge` itself.

**Shell/fill two-pass model (spec §6) mirrors quartifyr's conceptual
split but is not shared code with it.** quartifyr's pass 1 (shell) /
pass 2 (fill via `reportifyr`) is for `.docx`; deckifyr's own pass 1
(plan/shell) / pass 2 (resolve/compose) is for `.pptx` and does not call
`reportifyr`'s DOCX fill pipeline at all (spec §9.1) -- only its
documented `{rpfy}:` magic-string contract and metadata sidecars, via
deckifyr's own resolver (not yet implemented; see
`deckifyr.resolvers`'s module docstring).

**Every schema document requires an explicit `deckifyr:` version field
(spec §7.1), checked by one shared validator.**
`deckifyr.schema.version.check_schema_version()` is reused by all three
document models specifically so the supported-version set only needs
updating in one place as the schema evolves -- don't duplicate a
version check per model.

**`pyro` (and any other r-universe-only dependency) needs
`options(repos=)` to include `a2-ai.r-universe.dev`, and getting there
took three attempts against real CI/clean-sandbox failures -- two
plausible-looking fixes verifiably do not work.** quartifyr's CI adds
that repo via the `RENV_CONFIG_REPOS_OVERRIDE` env var, but that's
renv-specific; this repo's `r-check` job resolves deps via `pak`
(`r-lib/actions/setup-r-dependencies`), which never reads it -- first
attempt, failed on the first real push. DESCRIPTION's
`Additional_repositories:` field looked like the fix next (it's the
standard mechanism CRAN policy and `remotes::install_deps()` use for
exactly this), but `pak`'s `deps::.` local solve doesn't consult it
either -- confirmed in CI a second time. **The trap in "confirming"
either of these locally**: `pak` treats an already-installed package as
satisfying a dependency regardless of what's in `options(repos=)`, so
testing on a machine that already has `pyro` installed (true of this
repo's own dev environment) makes broken repo config look like it
works. The real test needs `pak::lockfile_create(..., lib =
"<empty-dir>")` to force a genuine repo resolution. The actual, verified
fix is this repo's root **`.Rprofile`**, which sets `options(repos=)`
directly and is sourced automatically by every plain `Rscript` step
(including `setup-r-dependencies`'s own) run from the repo root --
confirmed against a clean-lib sandbox before it went into CI. `pyro` is
deliberately *not* listed as an `any::pyro` extra package in `ci.yml`;
it only needs to be resolvable via `deps::.` (DESCRIPTION's `Imports:`),
same as any other real dependency.

**`deckifyr.renderers` and `deckifyr.web` are intentionally empty
packages with only a docstring; `deckifyr.pptx` no longer is.** Each
corresponds to a specific later phase in spec §18, and spec §20's
warnings 2/5/6 specifically caution against building the PPTX compositor
around Quarto's own layout writer, building the web editor before the
CLI/schema stabilize, or executing Quarto in an unisolated web process.
Read the relevant spec section before writing real code into either of
these two.

**Reference-PPTX policy (spec §21's open decision) is resolved
pragmatically for v1: `deckifyr.pptx.compose` uses `python-pptx`'s own
bundled default template, not a project-supplied reference file.** Every
`deckifyr build` starts from `pptx.Presentation()` with no arguments,
overrides `slide_width`/`slide_height` from `design.yaml`, and adds every
slide against that template's "Blank" native layout (found by name, spec
§10.1's "known blank or minimal native layout"). A project-supplied
reference `.pptx` (for a house theme, custom fonts baked into the
template, etc.) is a real future need but not what any current schema
field or CLI flag configures -- don't assume one is being read from
disk anywhere in `deckifyr.pptx` today.

**`deckifyr.plan` (Pass 1) and `deckifyr.pptx.compose` (Pass 2) stay
genuinely decoupled: `deckifyr.plan` has zero `python-pptx` import.**
This isn't just tidiness -- spec §6 keeps the two passes separate
specifically so a shell (the output of `expand_presentation`) can be
inspected or cached independent of whatever consumes it, and today's
`ResolvedElement`/`ResolvedSlide` dataclasses in `deckifyr/plan.py` are
that shell. Style tokens (`design.fonts`/`design.colors`) are resolved
to literal values during planning, not composition, for the same
reason: a `ResolvedElement` should be usable without `design.yaml` in
hand a second time. If you're adding a new element type, its
`SUPPORTED_ELEMENT_TYPES` membership and any zone/required semantics
belong in `deckifyr/plan.py`; only the actual `python-pptx` shape
construction belongs in `deckifyr/pptx/compose.py`.

**`tests/testthat/test-wiring.R`'s integration tests silently skip
under a real `R CMD check`/`covr::package_coverage()` run unless
`DECKIFYR_DEV_VENV_ROOT` is set -- confirmed empirically, not just
inferred.** `pyro::get_venv_uv_paths()` looks for `.venv/` at
`getOption("venv_dir")`, falling back to `here::here()` when unset.
`test_path("..", "..")` (what the test file used to rely on alone) and
`here::here()` both resolve relative to *where the test file currently
lives* -- fine when running `devtools::test()`/`testthat::test_dir()`
directly against this checkout, but `R CMD check` and `covr` both first
install the package into a *fresh, separate copy* and run
`tests/testthat.R` against that copy instead. Neither mechanism can
therefore ever find this checkout's `.venv/` (correctly excluded from
the package by `.Rbuildignore`) by relative path alone -- there is no
bug to fix in pyro or here::here() here, this is those tools' isolation
working as intended. The fix, in `test-wiring.R`: read
`Sys.getenv("DECKIFYR_DEV_VENV_ROOT")` (falling back to the old
`test_path("..", "..")` when unset, for local `devtools::test()` runs)
and pass it to `options(venv_dir = ...)` before any `deck_*()` call.
`ci.yml`'s `r-check`/`r-coverage` jobs set it to `${{ github.workspace
}}`. Without this, a real `R CMD check` reports the whole file skipped,
and `covr::package_coverage()` reports a flat 0% for every `R/*.R`
file -- both confirmed locally before this fix existed.

## Testing strategy

Today's tests are unit-level plus one true integration test:
`tests/python/` covers units/merge/schema/CLI exit codes in isolation,
plus `test_plan.py` (layout/slide expansion) and `test_pptx.py` (fit-mode
geometry, manifest shape, opening the written `.pptx` back up with
`python-pptx` to check slide/shape counts and names);
`tests/testthat/test-wiring.R` is the only test that actually invokes
the real R -> pyro -> Python bridge (the other two R-side gotchas above
were both caught by *running* this test against a live toolchain, not
by reasoning about the code). What's still missing from spec §17's later
categories: real visual-regression testing (rendering a slide to an
image and diffing it) and broader OOXML structural validation beyond
shape names/counts -- today's PPTX tests check what `python-pptx` can
read back, not what the file looks like rendered or its full
relationship-graph integrity.
