#' Inspect a presentation or .pptx
#'
#' Delegates to `deckifyr inspect` in the bundled Python engine. The
#' target type is detected from its file extension: a `.yaml`/`.yml`
#' presentation reports its resolved slide plan (element counts/types,
#' notes), while a `.pptx` reports its real, opened-back-up shape
#' structure (per slide: shape names/types, rotation, notes) plus a
#' summary of its sibling `<stem>.manifest.json`, if one exists.
#'
#' @param target Path to a `presentation.yaml` or a built `.pptx`.
#' @return A parsed list from the CLI's JSON output.
#' @examples
#' \dontrun{
#' deck_inspect("presentation.yaml")
#' deck_inspect("build/my-deck.pptx")
#' }
#' @export
deck_inspect <- function(target) {
  .run_deckifyr_cli(c("inspect", target))
}

#' Print a document type's JSON Schema
#'
#' Delegates to `deckifyr schema` in the bundled Python engine. This one
#' is fully functional today: it dumps the pydantic-generated JSON
#' Schema for `design`, `layouts`, or `presentation`.
#'
#' For IDE YAML tooling (e.g. VS Code's YAML extension, via a
#' `# yaml-language-server: $schema=...` comment or a `yaml.schemas`
#' setting) that needs a real file rather than this function's return
#' value, the same schemas also ship as static files at
#' `system.file("python", "deckifyr", "schemas", paste0(document,
#' ".schema.json"), package = "deckifyr")` (issue #49).
#'
#' @param document One of `"design"`, `"layouts"`, or `"presentation"`.
#' @return A parsed list representing the document type's JSON Schema.
#' @examples
#' \dontrun{
#' schema <- deck_schema("design")
#' schema$title
#' }
#' @export
deck_schema <- function(document = c("design", "layouts", "presentation")) {
  document <- match.arg(document)
  .run_deckifyr_cli(c("schema", document))
}

#' Launch the `deckifyr serve` background process
#'
#' Isolated behind its own function -- rather than calling
#' `processx::process$new()` directly inside [deck_serve()] -- specifically
#' so it's mockable: `testthat::local_mocked_bindings()` can only replace a
#' binding that already exists as a named object in a namespace/frame, and
#' `process$new` is an R6 generator method, not a plain function binding, so
#' it can't be intercepted that way (confirmed directly: mocking `new` via
#' `.package = "processx"` errors with "Can't find binding for `new`",
#' since `processx`'s own namespace never binds a bare `new` symbol). This
#' function is the one line that actually calls it, so tests fake this
#' function instead via `local_mocked_bindings(.launch_server_process = ...,
#' .env = environment())` -- the same "wrap the unmockable call in a small
#' internal function" seam this file's own `.wait_for_server()` uses for
#' `socketConnection()`, just applied to an R6 method instead of a base
#' function.
#'
#' Its own body is marked `# nocov` for the same reason it exists at all:
#' every unit test replaces this whole function (there's nothing finer to
#' mock, unlike e.g. `.run_deckifyr_cli()`'s own call to
#' `pyro::run_python_script()` -- an ordinary function, directly mockable
#' at the call site, so `.run_deckifyr_cli()`'s own body stays covered by
#' its mocked-pyro unit tests). The real `processx::process$new()` call
#' here only executes for real inside `tests/testthat/test-wiring.R`'s
#' gated end-to-end block, which needs a real `.venv`/`uv`/`pyro` install
#' and correctly skips without one -- including in `test-coverage.yaml`'s
#' own CI job, per this repo's already-established "an honest, accepted
#' coverage gap, not a problem to hide" precedent (CLAUDE.md).
#'
#' @param uv_path Path to the `uv` binary, from `pyro::get_venv_uv_paths()`.
#' @param args CLI arguments to pass to `uv` (`c("run", "-m", "deckifyr",
#'   "serve", ...)`).
#' @param env_vars Environment for the subprocess, in `processx`'s own
#'   `c("current", NAME = value, ...)` form.
#' @return A `processx::process` object, not yet awaited.
#' @keywords internal
.launch_server_process <- function(uv_path, args, env_vars) {
  # nocov start
  processx::process$new(
    command = uv_path,
    args = args,
    env = env_vars,
    stdout = "|",
    stderr = "|",
    cleanup = TRUE,
    # `uv run -m deckifyr serve ...` is a real parent/child pair, not one
    # process exec-replacing itself into the other -- confirmed directly
    # (spawn `uv run python -c 'time.sleep(30)'`, `pgrep -P` on the `uv`
    # PID lists a separate live `python3` PID underneath it). `cleanup`
    # alone only reaches the tracked `uv` PID; without `cleanup_tree`,
    # letting this handle get GC'd (R session exit, object dropped
    # without deck_stop_server()) kills `uv` but leaves the actual
    # `python -m deckifyr`/uvicorn process running, orphaned, still bound
    # to the port -- see deck_stop_server()'s own comment for the
    # explicit-kill half of this same fix.
    cleanup_tree = TRUE
  )
  # nocov end
}

#' Check whether something is already listening on `host`:`port`
#'
#' A plain TCP-connect probe -- never reads or writes anything, just
#' confirms a socket accepts connections. Shared by `.wait_for_server()`
#' (polls until this turns `TRUE`) and `deck_serve()`'s own pre-flight
#' check (refuses to launch when this is already `TRUE`, see that
#' function's own comment for the real bug this guards against).
#'
#' @param host,port The address to probe.
#' @return `TRUE`/`FALSE`.
#' @keywords internal
.port_is_open <- function(host, port) {
  # A refused connection attempt is expected, not exceptional --
  # socketConnection() both warns and errors on one, so the warning is
  # suppressed too, not just the error caught.
  conn <- tryCatch(
    suppressWarnings(socketConnection(host = host, port = port, open = "r", timeout = 1)),
    error = function(e) NULL
  )
  if (is.null(conn)) {
    return(FALSE)
  }
  close(conn)
  TRUE
}

#' Find the PID(s) of whatever process is listening on `port`
#'
#' Shells out to `lsof` (macOS/Linux) or PowerShell's
#' `Get-NetTCPConnection` (Windows, unverified on a real Windows machine
#' -- everything else in this file's port-by-PID helpers was confirmed
#' against a real spawned process on macOS, see `deck_stop_server()`'s
#' own docs) since neither base R nor `processx` expose a "who's
#' listening on this port" lookup -- there's no `processx::process`
#' handle to ask when the server wasn't launched by *this* R session
#' (a lost/overwritten `deckifyr_server` object, or a fresh session
#' entirely).
#'
#' @param port The port to look up.
#' @return An integer vector of PIDs (usually length 0 or 1).
#' @keywords internal
.pids_listening_on_port <- function(port) {
  if (identical(Sys.info()[["sysname"]], "Windows")) {
    # nocov start -- `test-coverage.yaml` (the only job that measures
    # coverage) runs on ubuntu-latest only; this branch is real, but
    # genuinely never measured, the same honest gap `.launch_server_process()`'s
    # own docs explain in more detail.
    out <- suppressWarnings(system2(
      "powershell",
      c(
        "-NoProfile", "-Command",
        sprintf(
          "(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue).OwningProcess",
          port
        )
      ),
      stdout = TRUE, stderr = FALSE
    ))
    # nocov end
  } else {
    if (!nzchar(Sys.which("lsof"))) {
      stop(
        "`lsof` is required to find a process by port on this platform ",
        "and wasn't found on PATH.",
        call. = FALSE
      )
    }
    out <- suppressWarnings(system2(
      "lsof", c("-ti", sprintf("TCP:%d", port), "-sTCP:LISTEN"),
      stdout = TRUE, stderr = FALSE
    ))
  }
  out <- suppressWarnings(as.integer(trimws(out)))
  out[!is.na(out)]
}

#' Does `pid`'s command line look like a `deckifyr serve` process?
#'
#' A same-process-tree safety check, not a strong guarantee -- just
#' enough to refuse to touch a process that plainly isn't ours before
#' [deck_serve()]'s `force = TRUE` or [deck_stop_server()]'s
#' `port =`/`host =` form ever kill anything found by port alone rather
#' than by a `processx` handle this session actually holds.
#'
#' @param pid A single PID.
#' @return `TRUE`/`FALSE` (`FALSE` if the PID doesn't exist any more).
#' @keywords internal
.pid_looks_like_deckifyr_server <- function(pid) {
  if (identical(Sys.info()[["sysname"]], "Windows")) {
    # nocov start -- see .pids_listening_on_port()'s own identical note.
    cmd <- suppressWarnings(system2(
      "powershell",
      c(
        "-NoProfile", "-Command",
        sprintf(
          "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" -ErrorAction SilentlyContinue).CommandLine",
          pid
        )
      ),
      stdout = TRUE, stderr = FALSE
    ))
    # nocov end
  } else {
    cmd <- suppressWarnings(system2(
      "ps", c("-o", "command=", "-p", as.character(pid)),
      stdout = TRUE, stderr = FALSE
    ))
  }
  cmd <- paste(cmd, collapse = " ")
  nzchar(cmd) && grepl("deckifyr", cmd, fixed = TRUE) && grepl("serve", cmd, fixed = TRUE)
}

#' Kill a `deckifyr serve` process found by PID, plus its `uv run` parent
#'
#' `pid` is the *listening* process (`python -m deckifyr`/uvicorn, what
#' `.pids_listening_on_port()` finds) -- its parent is ordinarily the
#' `uv run` wrapper that spawned it (confirmed directly, see
#' `deck_stop_server()`'s own docs on why `kill_tree()` exists at all).
#' Since this PID wasn't necessarily launched by this R session, there's
#' no `processx::process` handle and thus no `kill_tree()` to call --
#' this walks up to the parent manually instead, only killing it if
#' *its* command line also looks like a deckifyr server
#' (`.pid_looks_like_deckifyr_server()`), so a coincidental unrelated
#' parent process is never touched.
#'
#' @param pid The listening process's PID.
#' @keywords internal
.kill_deckifyr_server_pid <- function(pid) {
  if (identical(Sys.info()[["sysname"]], "Windows")) {
    # nocov start -- see .pids_listening_on_port()'s own identical note.
    # `/T` kills the whole process tree in one call -- no separate
    # parent-lookup step needed on this platform.
    system2("taskkill", c("/PID", as.character(pid), "/T", "/F"), stdout = FALSE, stderr = FALSE)
    return(invisible(NULL))
    # nocov end
  }
  ppid_raw <- suppressWarnings(system2(
    "ps", c("-o", "ppid=", "-p", as.character(pid)),
    stdout = TRUE, stderr = FALSE
  ))
  ppid <- suppressWarnings(as.integer(trimws(ppid_raw)))
  tools::pskill(pid, signal = tools::SIGKILL)
  if (length(ppid) == 1 && !is.na(ppid) && ppid > 1 && .pid_looks_like_deckifyr_server(ppid)) {
    tools::pskill(ppid, signal = tools::SIGKILL)
  }
  invisible(NULL)
}

#' Stop whatever deckifyr server is listening on `host`:`port`, if any
#'
#' Shared by [deck_stop_server()]'s `port =` form and [deck_serve()]'s
#' `force = TRUE` -- both need the same "find it, verify it's ours,
#' kill it" sequence. Refuses (via `stop()`) to kill anything whose
#' command line doesn't look like a deckifyr server, per-PID; never
#' silently skips a non-deckifyr occupant, since that would leave the
#' caller thinking the port is clear when it isn't.
#'
#' @param host,port The address to check.
#' @return `TRUE` if something was found and killed, `FALSE` if nothing
#'   was listening there at all.
#' @keywords internal
.stop_deckifyr_server_on_port <- function(host, port) {
  pids <- .pids_listening_on_port(port)
  if (length(pids) == 0) {
    return(invisible(FALSE))
  }
  is_ours <- vapply(pids, .pid_looks_like_deckifyr_server, logical(1))
  if (!all(is_ours)) {
    stop(
      sprintf(
        paste(
          "port %s on %s is in use by a process that doesn't look like a",
          "deckifyr server (pid %s) -- refusing to kill it. Stop it",
          "manually, or use a different port."
        ),
        port, host, paste(pids[!is_ours], collapse = ", ")
      ),
      call. = FALSE
    )
  }
  for (pid in pids) {
    .kill_deckifyr_server_pid(pid)
  }
  invisible(TRUE)
}

#' Poll a `deckifyr serve` process until it accepts connections
#'
#' A plain TCP-connect liveness check against `host`/`port` via
#' `.port_is_open()` -- it never reads or parses the HTTP response, just
#' confirms something is listening (the server's real readiness is
#' `GET /api/health`, but a successful connect is enough to know the
#' socket is bound). Polls every 0.2s; each iteration also checks
#' `process$is_alive()` first, so a process that crashed on startup (e.g.
#' the `web` extra isn't installed) is reported immediately, with its
#' captured stderr, rather than left to time out.
#'
#' @param host,port The address `deck_serve()` bound.
#' @param process The `processx::process` returned by
#'   `.launch_server_process()`.
#' @param timeout Seconds to wait before giving up.
#' @return `TRUE`, invisibly, once the server is reachable.
#' @keywords internal
.wait_for_server <- function(host, port, process, timeout) {
  deadline <- Sys.time() + timeout
  repeat {
    if (!process$is_alive()) {
      stderr_lines <- process$read_error_lines()
      stop(
        "deckifyr server process exited before becoming ready.\n  stderr: ",
        paste(stderr_lines, collapse = "\n"),
        call. = FALSE
      )
    }

    if (.port_is_open(host, port)) {
      return(invisible(TRUE))
    }

    if (Sys.time() >= deadline) {
      # kill_tree(), not kill() -- see deck_stop_server()'s own comment;
      # a process abandoned here mid-startup is exactly as capable of
      # being orphaned as one killed after a successful launch.
      process$kill_tree()
      stop(
        sprintf(
          "deckifyr server did not become ready within %ss (host=%s, port=%s).",
          timeout, host, port
        ),
        call. = FALSE
      )
    }
    Sys.sleep(0.2)
  }
}

#' Open a `deckifyr serve` URL in the RStudio/Positron Viewer or a browser
#'
#' Isolated behind its own function -- rather than inlined in
#' [deck_serve()] -- for the same reason `.launch_server_process()` is:
#' testability. `deck_serve()`'s own tests all pass `open_browser = FALSE`
#' and mock this function directly to assert it *would* have been called
#' with the right URL, rather than exercising the real
#' `rstudioapi`/`browseURL` branching through every one of them; this
#' function gets its own dedicated tests for that branching instead.
#'
#' @param url The server's URL.
#' @return `NULL`, invisibly.
#' @keywords internal
.open_server_url <- function(url) {
  if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
    rstudioapi::viewer(url)
  } else {
    utils::browseURL(url)
  }
  invisible(NULL)
}

#' Start the local web application
#'
#' Launches `deckifyr serve` in the bundled Python engine as a background
#' process via `processx` -- deliberately not `.run_deckifyr_cli()`, which
#' blocks until its subprocess exits and would hang forever against a
#' long-running server. Waits for the server to accept connections (up to
#' `timeout` seconds), then optionally opens its URL in a browser. Requires
#' the optional `web` extra (`fastapi`/`uvicorn`) to be installed in
#' deckifyr's bundled Python environment; if it isn't, the server process
#' exits immediately and that failure is surfaced with its captured stderr
#' rather than a generic timeout.
#'
#' Refuses to launch at all if `host`:`port` is already occupied
#' (`.port_is_open()`), rather than proceeding and letting
#' `.wait_for_server()`'s readiness poll connect to whatever is already
#' there. This is a real, confirmed failure mode, not a hypothetical: a
#' `deckifyr_server` handle whose process tree wasn't fully torn down
#' (fixed alongside this check -- `.launch_server_process()` now sets
#' `cleanup_tree = TRUE` and `deck_stop_server()` calls `kill_tree()`,
#' since `uv run -m deckifyr serve` is a real parent/child pair and
#' killing only the tracked `uv` PID left the actual Python/uvicorn
#' child running, orphaned, still bound to the port) left an old server
#' listening on the default port; a second `deck_serve()` call at the
#' same default port then had its own new process fail to bind (address
#' already in use) while `.wait_for_server()` still reported success --
#' because it was reconnecting to the *old*, stale server the whole
#' time, not the new one -- silently pointing the caller at the wrong
#' project with no error at all.
#'
#' `force = TRUE` additionally handles the port already being occupied
#' by an *existing* deckifyr server (as opposed to a genuinely
#' unrelated process, which it never touches, `force` or not): it looks
#' up the occupant by port (`.pids_listening_on_port()`), confirms its
#' command line actually looks like a deckifyr server
#' (`.pid_looks_like_deckifyr_server()`), and kills it before
#' proceeding -- the same "stop by port" mechanism [deck_stop_server()]
#' exposes directly, useful here specifically because the `deckifyr_server`
#' handle for that old server may no longer exist (a fresh R session, or
#' one where the object was simply lost) even though the process itself
#' is still running.
#'
#' @param project Path to the project directory to serve. Default `"."`.
#' @param host Host to bind. Default `"127.0.0.1"`.
#' @param port Port to bind. Default `8000`.
#' @param presentation `presentation.yaml` path, relative to `project`.
#'   Default `"presentation.yaml"`.
#' @param open_browser Open the server's URL once it's reachable -- via the
#'   RStudio Viewer pane when running inside RStudio, otherwise the system
#'   default browser. Default `TRUE`.
#' @param timeout Seconds to wait for the server to become reachable before
#'   giving up and killing the orphaned process. Default `15`.
#' @param force If `host`:`port` is already occupied by another deckifyr
#'   server, kill it first instead of erroring. Never kills a process that
#'   doesn't look like a deckifyr server, `force` or not. Default `FALSE`.
#' @return A `deckifyr_server` object (a list with class
#'   `"deckifyr_server"`): `process` (the `processx::process`), `host`,
#'   `port`, `url`, and `project`. Pass it to [deck_stop_server()] to shut
#'   the server down.
#' @examples
#' \dontrun{
#' server <- deck_serve(project = "my-deck")
#' deck_stop_server(server)
#'
#' # Restart on the same port without first tracking down the old handle:
#' server <- deck_serve(project = "my-deck", force = TRUE)
#' }
#' @export
deck_serve <- function(project = ".", host = "127.0.0.1", port = 8000,
                        presentation = "presentation.yaml",
                        open_browser = TRUE, timeout = 15, force = FALSE) {
  project <- normalizePath(project, mustWork = TRUE)

  if (.port_is_open(host, port)) {
    if (!isTRUE(force)) {
      stop(
        sprintf(
          paste(
            "port %s on %s is already in use -- a previous deckifyr server",
            "may still be running (call deck_stop_server() on its handle,",
            "deck_stop_server(port = %s), or pass force = TRUE to kill it",
            "automatically), or something else on this machine is using",
            "that port. Pass a different `port` to deck_serve() to work",
            "around it in the meantime."
          ),
          port, host, port
        ),
        call. = FALSE
      )
    }
    # .stop_deckifyr_server_on_port() itself refuses (via stop()) to
    # kill anything that doesn't look like a deckifyr server -- force
    # only ever means "don't ask before killing *our own* leftover
    # server", never "kill whatever's there".
    .stop_deckifyr_server_on_port(host, port)
    deadline <- Sys.time() + 5
    while (.port_is_open(host, port)) {
      if (Sys.time() >= deadline) {
        stop(
          sprintf(
            "port %s on %s did not free up after killing the existing deckifyr server.",
            port, host
          ),
          call. = FALSE
        )
      }
      Sys.sleep(0.2)
    }
  }

  python_src <- system.file("python", package = "deckifyr")
  if (!nzchar(python_src)) {
    stop(
      "deckifyr's bundled Python source (inst/python) was not found in ",
      "the installed package -- reinstall the deckifyr R package.",
      call. = FALSE
    )
  }

  paths <- pyro::get_venv_uv_paths()
  cli_args <- c(
    "run", "-m", "deckifyr", "serve",
    "--host", host, "--port", as.character(port),
    "--project", project, "--presentation", presentation,
    # Surfaced back via GET /api/health so the web editor's "no project
    # found" screen shows initialize_deck_project()/deck_serve() (R)
    # rather than deckifyr init/deckifyr serve (CLI) next-step
    # instructions -- see inst/python/deckifyr/web/app.py's own comment
    # on why this rides on /api/health specifically.
    "--launcher", "r"
  )
  env_vars <- c("current", VIRTUAL_ENV = paths$venv, PYTHONPATH = python_src)

  process <- .launch_server_process(paths$uv, cli_args, env_vars)
  .wait_for_server(host, port, process, timeout)

  url <- sprintf("http://%s:%s", host, port)
  if (isTRUE(open_browser)) {
    .open_server_url(url)
  }

  structure(
    list(process = process, host = host, port = port, url = url, project = project),
    class = "deckifyr_server"
  )
}

#' Stop a running deckifyr web server
#'
#' Kills the background process tree started by [deck_serve()] --
#' `kill_tree()`, not `kill()`: `uv run -m deckifyr serve` is a real
#' parent/child pair (`uv` spawns `python -m deckifyr`/uvicorn as a
#' genuine child process, confirmed directly, not something that
#' exec-replaces itself), so killing only the tracked top-level PID left
#' the actual server running, orphaned, still bound to the port -- a
#' real bug this fixes, not a hypothetical (see `deck_serve()`'s own
#' pre-flight-port-check comment for the confusing symptom it caused).
#'
#' Pass `port` instead of `server` to stop a deckifyr server whose
#' `deckifyr_server` handle no longer exists in this R session --
#' unlike `shiny::runApp()`, which hangs the calling session so
#' interrupting *that* is what stops the app, `deck_serve()`
#' deliberately returns control immediately (spec section 12.0's own
#' `shiny::runApp()`-*like*, not identical, mental model), so it's easy
#' to lose track of the object (a session restart, an overwritten
#' variable, ...) while the server itself keeps running. This form
#' looks up whatever's listening on `host`:`port`
#' (`.pids_listening_on_port()`) and refuses (with a clear error, not a
#' silent no-op) to kill it unless its command line actually looks like
#' a deckifyr server (`.pid_looks_like_deckifyr_server()`) -- it will
#' never kill an unrelated process just because it happens to occupy
#' that port.
#'
#' @param server A `deckifyr_server` object returned by [deck_serve()].
#'   Exactly one of `server`/`port` must be supplied.
#' @param port Stop whatever deckifyr server is listening on this port
#'   instead, without needing its `deckifyr_server` object. Exactly one
#'   of `server`/`port` must be supplied.
#' @param host Host to check when stopping by `port`. Default
#'   `"127.0.0.1"`, ignored when `server` is supplied (its own `$host`
#'   is used instead).
#' @return `server`, invisibly, when stopping by `server`; `invisible(NULL)`
#'   when stopping by `port` (there's no handle to return).
#' @examples
#' \dontrun{
#' server <- deck_serve(project = "my-deck")
#' deck_stop_server(server)
#'
#' # Or, if you've lost the `server` object but know the port:
#' deck_stop_server(port = 8000)
#' }
#' @export
deck_stop_server <- function(server = NULL, port = NULL, host = "127.0.0.1") {
  if (!is.null(server) && !is.null(port)) {
    stop("supply exactly one of `server` or `port`, not both.", call. = FALSE)
  }

  if (!is.null(server)) {
    if (!inherits(server, "deckifyr_server")) {
      stop(
        "`server` must be a `deckifyr_server` object returned by deck_serve().",
        call. = FALSE
      )
    }
    server$process$kill_tree()
    cli::cli_alert_success("Stopped deckifyr server at {.url {server$url}}")
    return(invisible(server))
  }

  if (is.null(port)) {
    stop("supply either `server` (a deckifyr_server object) or `port`.", call. = FALSE)
  }

  found <- .stop_deckifyr_server_on_port(host, port)
  if (!isTRUE(found)) {
    stop(
      sprintf("nothing is listening on port %s on %s.", port, host),
      call. = FALSE
    )
  }
  cli::cli_alert_success("Stopped deckifyr server on port {port}")
  invisible(NULL)
}

#' @export
print.deckifyr_server <- function(x, ...) {
  status <- if (x$process$is_alive()) "running" else "stopped"
  cli::cli_h3("deckifyr web server ({status})")
  cli::cli_bullets(c(
    "*" = "URL: {.url {x$url}}",
    "*" = "Project: {.file {x$project}}"
  ))
  invisible(x)
}
