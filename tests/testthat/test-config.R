# Unit coverage of deck_get_config()/deck_set_config()'s own arg-assembly
# logic, independent of a real pyro/uv toolchain -- see
# test-run-python.R's header comment for why these are mocked rather
# than end-to-end (test-wiring.R covers the real round trip).

test_that("deck_get_config() passes file and path through and returns $value", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(value = "#2457A6")
    }
  )

  result <- deck_get_config("design.yaml", "colors.primary")
  expect_equal(captured_args, c("get", "design.yaml", "colors.primary"))
  expect_equal(result, "#2457A6")
})

test_that("deck_set_config() defaults to auto type detection, no --string", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(file = "design.yaml")
    }
  )

  deck_set_config("design.yaml", "colors.primary", "#123456")
  expect_equal(
    captured_args,
    c("set", "design.yaml", "colors.primary", "#123456", "--type", "auto")
  )
})

test_that("deck_set_config() adds --string when as_string = TRUE", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(file = "presentation.yaml")
    }
  )

  deck_set_config("presentation.yaml", "metadata.status", "true", as_string = TRUE)
  expect_true("--string" %in% captured_args)
})

test_that("deck_set_config() passes an explicit type through", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(file = "presentation.yaml")
    }
  )

  deck_set_config("presentation.yaml", "build.previews", "true", type = "presentation")
  expect_equal(
    captured_args,
    c(
      "set", "presentation.yaml", "build.previews", "true",
      "--type", "presentation"
    )
  )
})

test_that("deck_set_config() rejects an unknown type", {
  expect_error(
    deck_set_config("design.yaml", "colors.primary", "#123456", type = "bogus")
  )
})
