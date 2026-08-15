# Unit coverage of deck_preview()'s arg-assembly; see
# test-run-python.R's header comment for why this is mocked. deck_preview
# always errors today (NotImplementedFeatureError, spec section 18 Phase
# 3) via the real CLI, but that "not implemented" behavior lives in
# Python, not this wrapper -- this test only proves the R side forwards
# the right args, matching how the other CLI wrappers are tested.

test_that("deck_preview() forwards presentation path to the CLI", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(status = "ok")
    }
  )

  deck_preview("presentation.yaml")
  expect_equal(captured_args, c("preview", "presentation.yaml"))
})
