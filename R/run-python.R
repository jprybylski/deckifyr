# testthat::local_mocked_bindings() can only replace a binding that
# already exists in this package's (locked, once installed) namespace --
# it can't create one. `system.file()` below is a base function called
# unqualified, so this NULL binding is the documented seam
# (`?testthat::local_mocked_bindings`, "Base functions") that lets tests
# mock it; it's shadowed by base::system.file() at runtime and never
# actually called. Kept as a plain (non-roxygen) comment/assignment so
# roxygen2 doesn't mistake it for the next block's documented object.
system.file <- NULL

#' Invoke the bundled Python CLI via pyro
#'
#' Internal helper every exported `deck_*()`/`initialize_deck_project()`
#' function funnels through -- the single bridge point, so schema/merge/
#' compiler logic is never reimplemented in R (see CLAUDE.md's "one
#' engine, two facades" note). Always requests `--json` output so
#' results come back as a parsed R list (spec section 11.2: "Return
#' structured R lists parsed from CLI JSON") rather than needing prose
#' scraping.
#'
#' **Why this isn't a thin wrapper around `pyro::run_python_script()`:**
#' confirmed against a real pyro install, `run_python_script()` calls
#' `processx::run(..., error_on_status = TRUE)` and, on any non-zero
#' exit, discards the captured stdout/stderr entirely and raises a bare
#' `"<script_name> failed."` -- so the deckifyr CLI's own diagnostic JSON
#' (which spec section 11.1 requires it to emit on schema/resolution/
#' composition failure, exit code != 0) would otherwise be lost. The fix
#' is `stderr_callback`: processx invokes it per output chunk *while the
#' process is still running*, before the exit-status check fires, so
#' output captured that way survives even when the call ultimately
#' errors. This only works because `deckifyr.cli` deliberately writes
#' its JSON error payload to stderr rather than stdout on the error path
#' -- see the matching comment in `inst/python/deckifyr/cli.py`'s
#' `main()`. Don't change one side of this handshake without the other.
#'
#' @param args Character vector of CLI arguments *after* `deckifyr`,
#'   e.g. `c("validate", "presentation.yaml")`.
#' @return A parsed list from the CLI's JSON output.
#' @keywords internal
.run_deckifyr_cli <- function(args) {
  python_src <- system.file("python", package = "deckifyr")
  if (!nzchar(python_src)) {
    stop(
      "deckifyr's bundled Python source (inst/python) was not found in ",
      "the installed package -- reinstall the deckifyr R package.",
      call. = FALSE
    )
  }

  paths <- pyro::get_venv_uv_paths()
  cli_args <- c("run", "-m", "deckifyr", "--json", args)

  stderr_lines <- character(0)
  capture_stderr <- function(chunk, proc) {
    stderr_lines <<- c(stderr_lines, chunk)
  }

  # `outcome` is either the list pyro::run_python_script() returns on
  # success, or the caught `error` condition on failure -- inspecting
  # its class below, rather than mutating an outer variable from inside
  # the tryCatch expression, sidesteps a real R scoping trap: a bare
  # `{ ... }` block passed as `expr` does NOT get its own environment,
  # so a `var <<- value` inside it (when `var` already exists in that
  # same enclosing frame) skips right past that local binding and
  # writes to a *further* enclosing scope instead. Confirmed the hard
  # way: an earlier version of this function used exactly that pattern
  # and silently left its "captured" stdout permanently NULL.
  outcome <- tryCatch(
    pyro::run_python_script(
      uv_path = paths$uv,
      venv_path = paths$venv,
      args = cli_args,
      script_name = "deckifyr",
      pythonpath = python_src,
      stderr_callback = capture_stderr
    ),
    error = function(e) e
  )

  command_desc <- paste("uv run -m deckifyr", paste(args, collapse = " "))

  if (inherits(outcome, "error")) {
    # The process exited non-zero; pyro's own error message is generic
    # ("deckifyr failed."), so recover the real diagnostic from the
    # stderr we captured via the callback above -- deckifyr.cli writes
    # exactly one JSON error object there on failure.
    stderr_text <- paste(stderr_lines, collapse = "")
    parsed_error <- tryCatch(
      jsonlite::fromJSON(stderr_text, simplifyVector = FALSE),
      error = function(e) NULL
    )
    if (!is.null(parsed_error) && identical(parsed_error$status, "error")) {
      stop(
        sprintf(
          "deckifyr %s failed [%s]: %s",
          args[[1]], parsed_error$code, parsed_error$message
        ),
        "\n  command: ", command_desc,
        call. = FALSE
      )
    }
    stop(
      "deckifyr ", args[[1]], " failed and did not produce a parseable ",
      "error payload.\n  command: ", command_desc, "\n  stderr: ", stderr_text,
      call. = FALSE
    )
  }

  parsed <- tryCatch(
    jsonlite::fromJSON(outcome$stdout, simplifyVector = FALSE),
    error = function(e) {
      stop(
        "deckifyr CLI exited successfully but did not return valid JSON.\n",
        "  command: ", command_desc, "\n",
        "  stdout: ", outcome$stdout,
        call. = FALSE
      )
    }
  )

  parsed
}
