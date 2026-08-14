# Proves the R -> pyro -> bundled-Python bridge actually works, not just
# that the R function signatures exist. Skips (rather than fails) when
# the toolchain isn't present, matching quartifyr's convention (see its
# CLAUDE.md) of skip-if-unavailable for tests that need a real R + uv +
# venv stack rather than mocking pyro.

skip_if_not_installed("pyro")

# `test_path("..", "..")` only resolves to the real repo checkout when
# these tests run directly against the source tree (devtools::test(),
# testthat::test_dir()). Under a real R CMD check or covr::
# package_coverage() run, this test file executes from a freshly staged
# copy of the package instead -- test_path() then resolves *inside* that
# staged copy, which has no .venv/ (correctly excluded by
# .Rbuildignore) and no examples/ (also excluded, dev-only content).
# pyro::get_venv_uv_paths() falls back to here::here() when
# options("venv_dir") is unset, which hits the exact same problem
# (here::here() finds the staged copy's own DESCRIPTION). Confirmed
# empirically: without this override, a real `R CMD check`/covr run
# always reports this whole file as skipped, and covr::package_coverage()
# reports 0% coverage for every R/*.R file -- not because the R -> pyro
# -> Python bridge doesn't work, but because there's no way for a process
# running from the staged copy to find the dev repo's .venv by relative
# path alone. CI sets DECKIFYR_DEV_VENV_ROOT to the real checkout path
# (see ci.yml) specifically so this test still exercises the real
# bridge under both check-r-package and test-coverage; local runs fall
# back to test_path() as before, unchanged.
repo_root <- Sys.getenv("DECKIFYR_DEV_VENV_ROOT", unset = test_path("..", ".."))
options(venv_dir = repo_root)

minimal_deck <- file.path(repo_root, "inst", "examples", "minimal-deck")
demo_deck <- file.path(repo_root, "examples", "demo-deck")

# pyro::get_venv_uv_paths() looks for an already-provisioned .venv/ at
# `options("venv_dir")` (set above) -- it does not create one itself,
# and it errors (not a skip-able condition on its own) if none exists.
# `uv sync --extra dev` (see CONTRIBUTING.md/ci.yml) provisions it; this
# is the same .venv/ the tests/python suite uses, not a separate
# pyro-specific one, confirmed locally: pyro is satisfied by a plain
# `uv run`-created venv with no `pyro::initialize_python()` call ever
# having run.
skip_if_not(
  dir.exists(file.path(repo_root, ".venv")),
  "repo .venv/ not provisioned (run `uv sync --extra dev` first)"
)

test_that("deck_validate() reports a valid project as valid", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  result <- deck_validate(file.path(minimal_deck, "presentation.yaml"))
  expect_true(result$valid)
  expect_equal(result$slide_count, 2)
})

test_that("deck_build() writes a real .pptx and manifest", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  # Build from a scratch copy rather than in place, so this test doesn't
  # leave a build/ directory inside the repo's bundled example (the same
  # fixture `deckifyr init`/`initialize_deck_project()` scaffolds from).
  project_dir <- file.path(tempdir(), "deckifyr-wiring-build")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)
  file.copy(
    file.path(minimal_deck, c("design.yaml", "layouts.yaml", "presentation.yaml")),
    project_dir
  )

  result <- deck_build(file.path(project_dir, "presentation.yaml"))
  expect_true(file.exists(result$output))
  expect_true(file.exists(result$manifest))
  expect_equal(result$slide_count, 2)
})

test_that("deck_build() builds the richer demo-deck example end to end", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  # examples/demo-deck (see its README.md) exercises a multi-zone layout,
  # a real reportifyr-produced image, rotation, and z_index together --
  # inst/examples/minimal-deck deliberately stays text/markdown-only.
  project_dir <- file.path(tempdir(), "deckifyr-wiring-demo-deck")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)
  for (entry in c("design.yaml", "layouts.yaml", "presentation.yaml", "OUTPUTS", "assets")) {
    file.copy(file.path(demo_deck, entry), project_dir, recursive = TRUE)
  }

  result <- deck_build(file.path(project_dir, "presentation.yaml"))
  expect_true(file.exists(result$output))
  expect_true(file.exists(result$manifest))
  expect_equal(result$slide_count, 3)
})
