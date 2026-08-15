# Unit coverage of deck_build()'s own arg-assembly logic; see
# test-run-python.R's header comment for why this is mocked.

test_that("deck_build() defaults to strict (no --warn-only)", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(output = "deck.pptx", manifest = "manifest.json", slide_count = 2)
    }
  )

  result <- deck_build("presentation.yaml")
  expect_equal(captured_args, c("build", "presentation.yaml"))
  expect_equal(result$slide_count, 2)
})

test_that("deck_build() adds --warn-only when strict = FALSE", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(output = "deck.pptx")
    }
  )

  deck_build("presentation.yaml", strict = FALSE)
  expect_equal(captured_args, c("build", "presentation.yaml", "--warn-only"))
})
