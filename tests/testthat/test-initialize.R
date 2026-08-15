# Unit coverage of initialize_deck_project()'s own orchestration logic
# (pyproject.toml provisioning + CLI arg assembly), independent of a
# real pyro/uv toolchain -- see test-run-python.R's header comment.

test_that("provisions the deckifyr dependency group before scaffolding", {
  provision_calls <- list()
  captured_args <- NULL

  local_mocked_bindings(
    write_group_to_pyproject = function(name, deps) {
      provision_calls[["write_group_to_pyproject"]] <<- list(name = name, deps = deps)
    },
    initialize_python = function(groups) {
      provision_calls[["initialize_python"]] <<- list(groups = groups)
    },
    .package = "pyro"
  )
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(created = c("design.yaml", "layouts.yaml", "presentation.yaml"))
    }
  )

  result <- initialize_deck_project("my-deck")

  expect_equal(provision_calls$write_group_to_pyproject$name, "deckifyr")
  expect_true("python-pptx" %in% provision_calls$write_group_to_pyproject$deps)
  expect_equal(provision_calls$initialize_python$groups, "deckifyr")
  expect_equal(captured_args, c("init", "my-deck"))
  expect_equal(result$created, c("design.yaml", "layouts.yaml", "presentation.yaml"))
})

test_that("defaults to the current directory and omits --force", {
  captured_args <- NULL
  local_mocked_bindings(
    write_group_to_pyproject = function(name, deps) invisible(NULL),
    initialize_python = function(groups) invisible(NULL),
    .package = "pyro"
  )
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(created = character(0))
    }
  )

  initialize_deck_project()
  expect_equal(captured_args, c("init", "."))
})

test_that("adds --force when requested", {
  captured_args <- NULL
  local_mocked_bindings(
    write_group_to_pyproject = function(name, deps) invisible(NULL),
    initialize_python = function(groups) invisible(NULL),
    .package = "pyro"
  )
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) {
      captured_args <<- args
      list(created = character(0))
    }
  )

  initialize_deck_project("my-deck", force = TRUE)
  expect_equal(captured_args, c("init", "my-deck", "--force"))
})

test_that("returns its result invisibly", {
  local_mocked_bindings(
    write_group_to_pyproject = function(name, deps) invisible(NULL),
    initialize_python = function(groups) invisible(NULL),
    .package = "pyro"
  )
  local_mocked_bindings(
    .run_deckifyr_cli = function(args) list(created = character(0))
  )

  expect_invisible(initialize_deck_project("my-deck"))
})
