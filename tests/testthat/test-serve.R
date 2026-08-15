# Unit coverage of deck_inspect()/deck_schema()'s arg-assembly (see
# test-run-python.R's header comment for why this is mocked rather than
# end-to-end), plus deck_serve()/deck_stop_server()'s own mechanics --
# the background-process launch, socket-based readiness polling, and both
# success/failure paths -- via mocked seams, independent of a real
# .venv/uv/pyro/web-extra toolchain. The real end-to-end proof of
# deck_serve()/deck_stop_server() (a genuine background server, polled and
# torn down for real) lives in tests/testthat/test-wiring.R's own last
# block, matching this suite's established mock-vs-real split (see
# CLAUDE.md's testing-strategy notes).

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

# A minimal fake `processx::process` -- a plain list exposing just the
# three methods deck_serve()/deck_stop_server()/.wait_for_server() call
# (`is_alive()`, `kill()`, `read_error_lines()`), plus a `was_killed()`
# test hook. `is_alive_values` is consumed one value per call to
# `is_alive()`; once exhausted, the last value repeats (mirrors a process
# settling into a final alive/dead state rather than oscillating).
make_fake_process <- function(is_alive_values, stderr_lines = character(0)) {
  calls <- 0L
  killed <- FALSE
  list(
    is_alive = function() {
      calls <<- calls + 1L
      idx <- min(calls, length(is_alive_values))
      is_alive_values[[idx]]
    },
    kill = function(...) {
      killed <<- TRUE
      invisible(TRUE)
    },
    read_error_lines = function(...) stderr_lines,
    was_killed = function() killed
  )
}

test_that(".wait_for_server() succeeds immediately when the socket connects", {
  local_mocked_bindings(socketConnection = function(...) textConnection(""))

  process <- make_fake_process(TRUE)
  expect_true(.wait_for_server("127.0.0.1", 8000, process, timeout = 5))
})

test_that(".wait_for_server() retries until the socket connects", {
  attempt <- 0L
  local_mocked_bindings(socketConnection = function(...) {
    attempt <<- attempt + 1L
    if (attempt < 3) {
      stop("connection refused")
    }
    textConnection("")
  })

  process <- make_fake_process(TRUE)
  expect_true(.wait_for_server("127.0.0.1", 8000, process, timeout = 5))
  expect_equal(attempt, 3L)
})

test_that(".wait_for_server() errors with the process's captured stderr when it dies", {
  local_mocked_bindings(socketConnection = function(...) stop("connection refused"))

  process <- make_fake_process(
    c(TRUE, FALSE),
    stderr_lines = c("Traceback (most recent call last):", "ImportError: fastapi")
  )

  expect_error(
    .wait_for_server("127.0.0.1", 8000, process, timeout = 5),
    "ImportError: fastapi"
  )
})

test_that(".wait_for_server() times out and kills the orphaned process", {
  local_mocked_bindings(socketConnection = function(...) stop("connection refused"))

  process <- make_fake_process(TRUE)
  expect_error(
    .wait_for_server("127.0.0.1", 8000, process, timeout = 0.1),
    "did not become ready within"
  )
  expect_true(process$was_killed())
})

test_that("deck_serve() launches the expected uv invocation and returns a deckifyr_server", {
  project_dir <- file.path(tempdir(), "deckifyr-serve-launch-test")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)

  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    .package = "pyro"
  )
  local_mocked_bindings(socketConnection = function(...) textConnection(""))

  captured <- NULL
  fake_process <- make_fake_process(TRUE)
  local_mocked_bindings(
    .launch_server_process = function(uv_path, args, env_vars) {
      captured <<- list(uv_path = uv_path, args = args, env_vars = env_vars)
      fake_process
    }
  )

  server <- deck_serve(
    project = project_dir, host = "127.0.0.1", port = 8321,
    presentation = "presentation.yaml", open_browser = FALSE
  )

  expect_s3_class(server, "deckifyr_server")
  expect_equal(server$host, "127.0.0.1")
  expect_equal(server$port, 8321)
  expect_equal(server$url, "http://127.0.0.1:8321")
  expect_equal(server$project, normalizePath(project_dir))
  expect_identical(server$process, fake_process)

  expect_equal(captured$uv_path, "fake-uv")
  expect_equal(
    captured$args,
    c(
      "run", "-m", "deckifyr", "serve",
      "--host", "127.0.0.1", "--port", "8321",
      "--project", normalizePath(project_dir),
      "--presentation", "presentation.yaml"
    )
  )
})

test_that("deck_stop_server() kills the process and reports success", {
  fake_process <- make_fake_process(TRUE)
  server <- structure(
    list(
      process = fake_process, host = "127.0.0.1", port = 8000,
      url = "http://127.0.0.1:8000", project = "/tmp/proj"
    ),
    class = "deckifyr_server"
  )

  expect_message(deck_stop_server(server), "Stopped deckifyr server")
  expect_true(fake_process$was_killed())
})

test_that("deck_stop_server() errors clearly on a non-deckifyr_server input", {
  expect_error(deck_stop_server(list()), "deckifyr_server")
})

test_that("print.deckifyr_server() reports status/url/project", {
  fake_process <- make_fake_process(TRUE)
  server <- structure(
    list(
      process = fake_process, host = "127.0.0.1", port = 8000,
      url = "http://127.0.0.1:8000", project = "/tmp/proj"
    ),
    class = "deckifyr_server"
  )

  expect_message(print(server), "running")
  expect_message(print(server), "http://127.0.0.1:8000")
})
