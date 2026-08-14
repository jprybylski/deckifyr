# Proves the R -> pyro -> bundled-Python bridge actually works, not just
# that the R function signatures exist. Skips (rather than fails) when
# the toolchain isn't present, matching quartifyr's convention (see its
# CLAUDE.md) of skip-if-unavailable for tests that need a real R + uv +
# venv stack rather than mocking pyro.

skip_if_not_installed("pyro")

repo_root <- test_path("..", "..")
minimal_deck <- file.path(repo_root, "inst", "examples", "minimal-deck")
demo_deck <- file.path(repo_root, "examples", "demo-deck")

# pyro::get_venv_uv_paths() looks for an already-provisioned .venv/ at
# the project root -- it does not create one itself, and it errors
# (not a skip-able condition on its own) if none exists. `uv sync
# --extra dev` (see CONTRIBUTING.md/ci.yml) provisions it; this is the
# same .venv/ the tests/python suite uses, not a separate pyro-specific
# one, confirmed locally: pyro is satisfied by a plain `uv run`-created
# venv with no `pyro::initialize_python()` call ever having run.
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
