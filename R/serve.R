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
#' @param uv_path Path to the `uv` binary, from `pyro::get_venv_uv_paths()`.
#' @param args CLI arguments to pass to `uv` (`c("run", "-m", "deckifyr",
#'   "serve", ...)`).
#' @param env_vars Environment for the subprocess, in `processx`'s own
#'   `c("current", NAME = value, ...)` form.
#' @return A `processx::process` object, not yet awaited.
#' @keywords internal
.launch_server_process <- function(uv_path, args, env_vars) {
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
#' @return A `deckifyr_server` object (a list with class
#'   `"deckifyr_server"`): `process` (the `processx::process`), `host`,
#'   `port`, `url`, and `project`. Pass it to [deck_stop_server()] to shut
#'   the server down.
#' @examples
#' \dontrun{
#' server <- deck_serve(project = "my-deck")
#' deck_stop_server(server)
#' }
#' @export
deck_serve <- function(project = ".", host = "127.0.0.1", port = 8000,
                        presentation = "presentation.yaml",
                        open_browser = TRUE, timeout = 15) {
  project <- normalizePath(project, mustWork = TRUE)

  if (.port_is_open(host, port)) {
    stop(
      sprintf(
        paste(
          "port %s on %s is already in use -- a previous deckifyr server",
          "may still be running (call deck_stop_server() on its handle,",
          "or find and stop the orphaned process manually), or something",
          "else on this machine is using that port. Pass a different",
          "`port` to deck_serve() to work around it in the meantime."
        ),
        port, host
      ),
      call. = FALSE
    )
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
    if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
      rstudioapi::viewer(url)
    } else {
      utils::browseURL(url)
    }
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
#' @param server A `deckifyr_server` object returned by [deck_serve()].
#' @return `server`, invisibly.
#' @examples
#' \dontrun{
#' server <- deck_serve(project = "my-deck")
#' deck_stop_server(server)
#' }
#' @export
deck_stop_server <- function(server) {
  if (!inherits(server, "deckifyr_server")) {
    stop(
      "`server` must be a `deckifyr_server` object returned by deck_serve().",
      call. = FALSE
    )
  }
  server$process$kill_tree()
  cli::cli_alert_success("Stopped deckifyr server at {.url {server$url}}")
  invisible(server)
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
