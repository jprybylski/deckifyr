# Proves the R -> pyro -> bundled-Python bridge actually works, not just
# that the R function signatures exist. Skips (rather than fails) when
# the toolchain isn't present, matching quartifyr's convention (see its
# CLAUDE.md) of skip-if-unavailable for tests that need a real R + uv +
# venv stack rather than mocking pyro.

skip_if_not_installed("pyro")

repo_root <- test_path("..", "..")
minimal_deck <- file.path(repo_root, "inst", "examples", "minimal-deck")

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

test_that("deck_build() surfaces the not-implemented error from Python", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  expect_error(
    deck_build(file.path(minimal_deck, "presentation.yaml")),
    "not implemented"
  )
})
