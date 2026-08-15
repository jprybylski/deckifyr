# Unit coverage of deck_inspect()/deck_schema()/deck_serve()'s
# arg-assembly; see test-run-python.R's header comment for why this is
# mocked rather than end-to-end.

test_that("deck_inspect() forwards the target path to the CLI", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(status = "ok")
    }
  )

  deck_inspect("deck.pptx")
  expect_equal(captured_args, c("inspect", "deck.pptx"))
})

test_that("deck_schema() defaults to 'design' and validates its choices", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(type = "object")
    }
  )

  deck_schema()
  expect_equal(captured_args, c("schema", "design"))

  deck_schema("presentation")
  expect_equal(captured_args, c("schema", "presentation"))

  deck_schema("layouts")
  expect_equal(captured_args, c("schema", "layouts"))

  expect_error(deck_schema("not-a-real-document"))
})

test_that("deck_serve() forwards host/port, including non-default values", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(status = "ok")
    }
  )

  deck_serve()
  expect_equal(captured_args, c("serve", "--host", "127.0.0.1", "--port", "8000"))

  deck_serve(host = "0.0.0.0", port = 9001)
  expect_equal(captured_args, c("serve", "--host", "0.0.0.0", "--port", "9001"))
})
