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
# (`is_alive()`, `kill_tree()`, `read_error_lines()`), plus a
# `was_killed()` test hook. `is_alive_values` is consumed one value per
# call to `is_alive()`; once exhausted, the last value repeats (mirrors a
# process settling into a final alive/dead state rather than
# oscillating). `kill_tree()`, not `kill()`, matches the real fix this
# file covers: killing only the tracked `uv` PID left its actual
# python/uvicorn child running, orphaned (see deck_stop_server()'s own
# docs for the confirmed real bug).
make_fake_process <- function(is_alive_values, stderr_lines = character(0)) {
  calls <- 0L
  killed <- FALSE
  list(
    is_alive = function() {
      calls <<- calls + 1L
      idx <- min(calls, length(is_alive_values))
      is_alive_values[[idx]]
    },
    kill_tree = function(...) {
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

# Helper to put this session on the non-Windows (lsof/ps) branch of
# every port-by-PID function below, regardless of the actual OS running
# the tests.
local_mock_unix <- function(env = parent.frame()) {
  local_mocked_bindings(Sys.info = function() c(sysname = "Darwin"), .env = env)
}

test_that(".pids_listening_on_port() parses lsof's newline-separated PIDs", {
  local_mock_unix()
  local_mocked_bindings(Sys.which = function(...) "/usr/sbin/lsof")
  captured <- NULL
  local_mocked_bindings(system2 = function(command, args, ...) {
    captured <<- list(command = command, args = args)
    c("29095", "29200")
  })

  pids <- .pids_listening_on_port(8351)

  expect_equal(pids, c(29095L, 29200L))
  expect_equal(captured$command, "lsof")
  expect_equal(captured$args, c("-ti", "TCP:8351", "-sTCP:LISTEN"))
})

test_that(".pids_listening_on_port() returns an empty vector when nothing is listening", {
  local_mock_unix()
  local_mocked_bindings(Sys.which = function(...) "/usr/sbin/lsof")
  local_mocked_bindings(system2 = function(...) character(0))

  expect_equal(.pids_listening_on_port(8351), integer(0))
})

test_that(".pids_listening_on_port() errors clearly when lsof isn't on PATH", {
  local_mock_unix()
  local_mocked_bindings(Sys.which = function(...) "")

  expect_error(.pids_listening_on_port(8351), "lsof")
})

test_that(".pid_looks_like_deckifyr_server() checks for both 'deckifyr' and 'serve'", {
  local_mock_unix()
  local_mocked_bindings(system2 = function(...) {
    "/Users/x/.venv/bin/python3 -m deckifyr serve --host 127.0.0.1 --port 8351"
  })
  expect_true(.pid_looks_like_deckifyr_server(29095))

  local_mocked_bindings(system2 = function(...) "/usr/bin/some-other-process --flag")
  expect_false(.pid_looks_like_deckifyr_server(1234))

  local_mocked_bindings(system2 = function(...) character(0))
  expect_false(.pid_looks_like_deckifyr_server(99999))
})

test_that(".kill_deckifyr_server_pid() kills the pid and its deckifyr-looking parent", {
  local_mock_unix()
  ps_calls <- list()
  pskill_calls <- list()
  local_mocked_bindings(system2 = function(command, args, ...) {
    ps_calls[[length(ps_calls) + 1L]] <<- list(command = command, args = args)
    if (identical(args, c("-o", "ppid=", "-p", "29095"))) {
      return("29094")
    }
    if (identical(args, c("-o", "command=", "-p", "29094"))) {
      return("uv run -m deckifyr serve --host 127.0.0.1 --port 8351")
    }
    character(0)
  })
  local_mocked_bindings(
    pskill = function(pid, signal) {
      pskill_calls[[length(pskill_calls) + 1L]] <<- list(pid = pid, signal = signal)
      invisible(TRUE)
    },
    .package = "tools"
  )

  .kill_deckifyr_server_pid(29095)

  killed_pids <- vapply(pskill_calls, function(x) x$pid, numeric(1))
  expect_setequal(killed_pids, c(29095, 29094))
})

test_that(".kill_deckifyr_server_pid() does not kill an unrelated parent process", {
  local_mock_unix()
  local_mocked_bindings(system2 = function(command, args, ...) {
    if (identical(args, c("-o", "ppid=", "-p", "29095"))) {
      return("500")
    }
    if (identical(args, c("-o", "command=", "-p", "500"))) {
      return("/bin/zsh")
    }
    character(0)
  })
  pskill_calls <- list()
  local_mocked_bindings(
    pskill = function(pid, signal) {
      pskill_calls[[length(pskill_calls) + 1L]] <<- pid
      invisible(TRUE)
    },
    .package = "tools"
  )

  .kill_deckifyr_server_pid(29095)

  expect_equal(unlist(pskill_calls), 29095L)
})

test_that(".stop_deckifyr_server_on_port() returns FALSE when nothing is listening", {
  local_mock_unix()
  local_mocked_bindings(Sys.which = function(...) "/usr/sbin/lsof")
  local_mocked_bindings(system2 = function(...) character(0))

  expect_false(.stop_deckifyr_server_on_port("127.0.0.1", 8351))
})

test_that(".stop_deckifyr_server_on_port() refuses to kill a non-deckifyr occupant", {
  local_mock_unix()
  local_mocked_bindings(Sys.which = function(...) "/usr/sbin/lsof")
  local_mocked_bindings(system2 = function(command, args, ...) {
    if (identical(command, "lsof")) return("4242")
    if (identical(args, c("-o", "command=", "-p", "4242"))) return("/usr/bin/some-other-server")
    character(0)
  })
  pskill_called <- FALSE
  local_mocked_bindings(
    pskill = function(...) {
      pskill_called <<- TRUE
    },
    .package = "tools"
  )

  expect_error(.stop_deckifyr_server_on_port("127.0.0.1", 8351), "doesn't look like a")
  expect_false(pskill_called)
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
  # Two-phase: deck_serve()'s own pre-flight check must see the port as
  # free (the first call) before it ever launches anything, then
  # .wait_for_server()'s readiness poll (every call after) must see it
  # as open once the fake process is "running".
  socket_calls <- 0L
  local_mocked_bindings(socketConnection = function(...) {
    socket_calls <<- socket_calls + 1L
    if (socket_calls == 1L) stop("connection refused")
    textConnection("")
  })

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
      "--presentation", "presentation.yaml",
      "--launcher", "r"
    )
  )
})

test_that("deck_serve() refuses to launch when the port is already occupied", {
  project_dir <- file.path(tempdir(), "deckifyr-serve-port-busy-test")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)

  # The port always looks open -- simulating a leftover/orphaned server
  # (real bug: this used to let .wait_for_server() falsely report
  # success by reconnecting to that stale server instead of the doomed
  # new one, silently pointing the caller at the wrong project).
  local_mocked_bindings(socketConnection = function(...) textConnection(""))

  launched <- FALSE
  local_mocked_bindings(
    .launch_server_process = function(...) {
      launched <<- TRUE
      stop("must not be called -- the port pre-flight check should have stopped first")
    }
  )

  expect_error(
    deck_serve(project = project_dir, port = 8321, open_browser = FALSE),
    "already in use"
  )
  expect_false(launched)
})

test_that("deck_serve(force = TRUE) kills an existing deckifyr server on that port, then launches", {
  project_dir <- file.path(tempdir(), "deckifyr-serve-force-test")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)

  local_mocked_bindings(`system.file` = function(...) "/fake/python/src")
  local_mocked_bindings(
    get_venv_uv_paths = function() list(uv = "fake-uv", venv = "fake-venv"),
    .package = "pyro"
  )

  # 1st call: deck_serve()'s own pre-flight check (port busy -- an
  # existing server is there). 2nd call: the post-kill wait loop (port
  # now free). 3rd+ call: .wait_for_server()'s own readiness poll for
  # the newly-launched process (port open again).
  socket_calls <- 0L
  local_mocked_bindings(socketConnection = function(...) {
    socket_calls <<- socket_calls + 1L
    if (socket_calls == 2L) stop("connection refused")
    textConnection("")
  })

  stopped_existing <- FALSE
  local_mocked_bindings(
    .stop_deckifyr_server_on_port = function(host, port) {
      stopped_existing <<- TRUE
      TRUE
    }
  )

  fake_process <- make_fake_process(TRUE)
  launched <- FALSE
  local_mocked_bindings(
    .launch_server_process = function(...) {
      launched <<- TRUE
      fake_process
    }
  )

  server <- deck_serve(
    project = project_dir, port = 8321, force = TRUE, open_browser = FALSE
  )

  expect_true(stopped_existing)
  expect_true(launched)
  expect_s3_class(server, "deckifyr_server")
})

test_that("deck_stop_server(port = ) stops whatever's listening there", {
  local_mocked_bindings(
    .stop_deckifyr_server_on_port = function(host, port) {
      expect_equal(host, "127.0.0.1")
      expect_equal(port, 8351)
      TRUE
    }
  )

  expect_message(deck_stop_server(port = 8351), "Stopped deckifyr server on port")
})

test_that("deck_stop_server(port = ) errors clearly when nothing is listening there", {
  local_mocked_bindings(.stop_deckifyr_server_on_port = function(host, port) FALSE)

  expect_error(deck_stop_server(port = 8351), "nothing is listening")
})

test_that("deck_stop_server() rejects both server and port, or neither", {
  fake_server <- structure(list(), class = "deckifyr_server")
  expect_error(deck_stop_server(server = fake_server, port = 8000), "exactly one")
  expect_error(deck_stop_server(), "either")
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
