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

# issue #34: template-based init -- --from-dir/--from-repo/--ref/--subdir/
# --type each individually forwarded as a "--flag value" pair, with no
# R-side business-rule validation (mutual exclusivity, --type requiring
# --from-dir/--from-repo, ...) -- that lives only in the Python CLI, so
# these tests only assert argument forwarding.

test_that("forwards --from-dir when given", {
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

  initialize_deck_project("my-deck", from_dir = "../org-templates")
  expect_equal(captured_args, c("init", "my-deck", "--from-dir", "../org-templates"))
})

test_that("forwards --from-repo, --ref, --subdir, and --type when given", {
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

  initialize_deck_project(
    "my-deck",
    from_repo = "acme-org/deck-templates",
    ref = "v2",
    subdir = "templates/quarterly-review",
    type = "quarterly-review"
  )
  expect_equal(
    captured_args,
    c(
      "init", "my-deck",
      "--from-repo", "acme-org/deck-templates",
      "--ref", "v2",
      "--subdir", "templates/quarterly-review",
      "--type", "quarterly-review"
    )
  )
})

test_that("forwards --ref alone (without --subdir or --type)", {
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

  initialize_deck_project("my-deck", from_repo = "acme-org/deck-templates", ref = "v2")
  expect_equal(
    captured_args,
    c("init", "my-deck", "--from-repo", "acme-org/deck-templates", "--ref", "v2")
  )
})

test_that("forwards --subdir alone (without --ref or --type)", {
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

  initialize_deck_project(
    "my-deck",
    from_repo = "acme-org/deck-templates",
    subdir = "templates/quarterly-review"
  )
  expect_equal(
    captured_args,
    c(
      "init", "my-deck",
      "--from-repo", "acme-org/deck-templates",
      "--subdir", "templates/quarterly-review"
    )
  )
})

test_that("forwards --type alone (without --ref or --subdir)", {
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

  initialize_deck_project(
    "my-deck",
    from_dir = "../org-templates",
    type = "quarterly-review"
  )
  expect_equal(
    captured_args,
    c("init", "my-deck", "--from-dir", "../org-templates", "--type", "quarterly-review")
  )
})

test_that("omits every new flag when the new parameters are left NULL", {
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

  initialize_deck_project("my-deck")
  expect_equal(captured_args, c("init", "my-deck"))
})
