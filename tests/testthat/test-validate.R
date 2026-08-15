# Unit coverage of deck_validate()'s own arg-assembly logic (strict vs
# --warn-only), independent of a real pyro/uv toolchain -- see
# test-run-python.R's header comment for why these are mocked rather
# than end-to-end.

test_that("deck_validate() defaults to strict (no --warn-only)", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(valid = TRUE)
    }
  )

  result <- deck_validate("presentation.yaml")
  expect_equal(captured_args, c("validate", "presentation.yaml"))
  expect_true(result$valid)
})

test_that("deck_validate() adds --warn-only when strict = FALSE", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(valid = TRUE)
    }
  )

  deck_validate("presentation.yaml", strict = FALSE)
  expect_equal(captured_args, c("validate", "presentation.yaml", "--warn-only"))
})
