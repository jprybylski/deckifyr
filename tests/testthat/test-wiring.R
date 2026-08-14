# Proves the R -> pyro -> bundled-Python bridge actually works, not just
# that the R function signatures exist. Skips (rather than fails) when
# the toolchain isn't present, matching quartifyr's convention (see its
# CLAUDE.md) of skip-if-unavailable for tests that need a real R + uv +
# venv stack rather than mocking pyro.

skip_if_not_installed("pyro")

minimal_deck <- test_path("..", "..", "inst", "examples", "minimal-deck")

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
