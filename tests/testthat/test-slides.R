# Unit coverage of the deck_*_slide() family's own arg-assembly logic,
# independent of a real pyro/uv toolchain -- see test-run-python.R's
# header comment for why these are mocked (test-wiring.R covers the real
# round trip for deck_validate()/deck_build(); the slide-editing family
# isn't duplicated there since its own mechanism -- deckifyr.editor -- is
# already covered end to end by tests/python/test_cli_editing.py).

test_that(".placement_args() rejects more than one of after/before/index", {
  expect_error(.placement_args("a", "b", NULL), "at most one")
  expect_error(.placement_args("a", NULL, 1), "at most one")
  expect_error(.placement_args(NULL, "b", 1), "at most one")
})

test_that(".placement_args() returns the right flag for each argument", {
  expect_equal(.placement_args("a", NULL, NULL), c("--after", "a"))
  expect_equal(.placement_args(NULL, "b", NULL), c("--before", "b"))
  expect_equal(.placement_args(NULL, NULL, 2), c("--index", "2"))
  expect_equal(.placement_args(NULL, NULL, NULL), character(0))
})

test_that("deck_list_slides() returns $slides and can stay quiet", {
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      list(slides = list(
        list(id = "a", layout = "blank", element_count = 1L, has_notes = FALSE)
      ))
    }
  )

  result <- deck_list_slides("presentation.yaml", quiet = TRUE)
  expect_equal(result[[1]]$id, "a")
})

test_that("deck_add_slide() assembles id/layout/notes/placement flags", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 3)
    }
  )

  deck_add_slide(
    "presentation.yaml", id = "new", layout = "blank",
    notes = "hi", after = "title"
  )
  expect_equal(
    captured_args,
    c(
      "slide", "add", "presentation.yaml", "--id", "new",
      "--layout", "blank", "--notes", "hi", "--after", "title"
    )
  )
})

test_that("deck_add_slide() encodes elements as JSON", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_add_slide(
    "presentation.yaml", id = "new",
    elements = list(title = list(value = "Hi"))
  )
  json_arg <- captured_args[which(captured_args == "--elements-json") + 1]
  expect_equal(jsonlite::fromJSON(json_arg)$title$value, "Hi")
})

test_that("deck_add_slide() omits layout/notes flags when unset", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_add_slide("presentation.yaml", id = "new")
  expect_equal(captured_args, c("slide", "add", "presentation.yaml", "--id", "new"))
})

test_that("deck_remove_slide() passes presentation and id through", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_remove_slide("presentation.yaml", "old-slide")
  expect_equal(captured_args, c("slide", "remove", "presentation.yaml", "old-slide"))
})

test_that("deck_update_slide() uses --no-layout/--clear-notes for NA", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_update_slide("presentation.yaml", "a", layout = NA, notes = NA)
  expect_equal(
    captured_args,
    c("slide", "update", "presentation.yaml", "a", "--no-layout", "--clear-notes")
  )
})

test_that("deck_update_slide() uses --layout/--notes for non-NA values", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_update_slide("presentation.yaml", "a", layout = "new-layout", notes = "new notes")
  expect_equal(
    captured_args,
    c(
      "slide", "update", "presentation.yaml", "a",
      "--layout", "new-layout", "--notes", "new notes"
    )
  )
})

test_that("deck_update_slide() leaves layout/notes untouched when NULL", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 1)
    }
  )

  deck_update_slide("presentation.yaml", "a")
  expect_equal(captured_args, c("slide", "update", "presentation.yaml", "a"))
})

test_that("deck_move_slide() assembles placement flags", {
  captured_args <- NULL
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(slide_count = 2)
    }
  )

  deck_move_slide("presentation.yaml", "a", index = 0)
  expect_equal(
    captured_args,
    c("slide", "move", "presentation.yaml", "a", "--index", "0")
  )
})
