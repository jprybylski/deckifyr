# testthat::local_mocked_bindings() can only replace a binding that
# already exists in this package's (locked, once installed) namespace --
# it can't create one. `system.file()` below is a base function called
# unqualified, so this NULL binding is the documented seam
# (`?testthat::local_mocked_bindings`, "Base functions") that lets tests
# mock it; it's shadowed by base::system.file() at runtime and never
# actually called. Kept as a plain (non-roxygen) comment/assignment so
# roxygen2 doesn't mistake it for the next block's documented object.
system.file <- NULL

# Same seam, same reason, for the four base functions
# `.handle_missing_dependency()`'s Homebrew-install branch calls
# unqualified: without these, testthat's tests could observe the
# "declined/non-interactive" fallback (real `interactive()` is FALSE
# under testthat anyway) but never the "accepted" branch --
# `Sys.info()`/`Sys.which()`/`interactive()`/`system()` would need to be
# genuinely faked at the OS level otherwise. `utils::askYesNo` doesn't
# need this treatment: it's called `::`-qualified, so
# `local_mocked_bindings(.package = "utils")` already works on it
# directly, the same way `pyro::run_python_script` is mocked elsewhere
# in this file's own tests.
interactive <- NULL
system <- NULL
Sys.info <- NULL
Sys.which <- NULL

# Same seam, same reason, for `deck_serve()`'s `.wait_for_server()`
# (`R/serve.R`), which calls unqualified `socketConnection()` as a plain
# TCP-connect readiness check.
socketConnection <- NULL

# Same seam, same reason, for `.open_server_url()` (`R/serve.R`), which
# calls unqualified `requireNamespace()` to soft-check for the optional
# `rstudioapi` package.
requireNamespace <- NULL

# Same seam, same reason, for `R/serve.R`'s port-by-PID helpers
# (`.pids_listening_on_port()`/`.pid_looks_like_deckifyr_server()`/
# `.kill_deckifyr_server_pid()`), which shell out via unqualified
# `system2()` (`lsof`/`ps`/`taskkill`/`powershell`) to find and kill a
# deckifyr server process this R session doesn't hold a `processx`
# handle for.
system2 <- NULL

# Same seam, same reason, for `deck_serve()`'s `force = TRUE` port-freed
# wait loop (`R/serve.R`), which calls unqualified `Sys.time()` to poll a
# deadline -- lets a test simulate the deadline passing without a real
# multi-second sleep.
Sys.time <- NULL

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
      if (identical(parsed_error$code, "E_MISSING_DEPENDENCY") &&
        !is.null(parsed_error$dependency)) {
        .handle_missing_dependency(parsed_error$dependency)
      }
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

# The exact Homebrew cask name for each dependency `name` the Python
# engine's `MissingDependencyError` can carry (`inst/python/deckifyr/
# schema/errors.py`) -- confirmed against Homebrew's own cask listings
# (formulae.brew.sh/cask/libreoffice, formulae.brew.sh/cask/quarto), not
# guessed. `NULL` for anything else (there is currently nothing else),
# so `.handle_missing_dependency()` below always falls back to printing
# the install URL rather than assuming a cask name that doesn't exist.
.homebrew_cask_for_dependency <- function(name) {
  switch(name,
    soffice = "libreoffice",
    quarto = "quarto",
    NULL
  )
}

#' Print install guidance for a missing external binary dependency
#'
#' Called from `.run_deckifyr_cli()` when the Python CLI's JSON error
#' payload carries a `dependency` object (`code == "E_MISSING_DEPENDENCY"`,
#' `deckifyr.schema.errors.MissingDependencyError` -- see its own
#' docstring) -- today, a missing `soffice` (LibreOffice, `deck_preview()`)
#' or `quarto` (Quarto, any build touching a `type: quarto` element)
#' binary. Always prints a `cli`-formatted panel naming the dependency
#' and its official download page; on macOS, with Homebrew already on
#' `PATH`, in an interactive session, additionally offers to run the
#' known-correct `brew install --cask <name>` command itself (no `sudo`
#' needed, so safe to run without extra privilege escalation) -- every
#' other platform, or a non-interactive session (this repo's own test
#' suite included, so tests never actually shell out to Homebrew), or a
#' machine without Homebrew, just gets the printed URL: there's no
#' single install command deckifyr can verify in advance for apt/winget/
#' etc, and this deliberately never guesses one or runs anything that
#' needs `sudo`. A failed/declined/skipped install attempt does not
#' retry the original `deckifyr` command -- the caller's own `stop()`
#' (right after this runs) still fires either way, so the user re-runs
#' their command themselves once the dependency is actually installed;
#' this machine may also have no network access to Homebrew's own
#' servers at all (firewalled/offline), so the install attempt is
#' wrapped in `tryCatch()` and reported as a failure rather than
#' crashing this function.
#'
#' @param dependency A list with `name`/`display_name`/`install_url`,
#'   parsed straight from the CLI's JSON `dependency` object.
#' @keywords internal
.handle_missing_dependency <- function(dependency) {
  cli::cli_h3("Missing dependency: {dependency$display_name}")
  cli::cli_bullets(c("i" = "Download/install: {.url {dependency$install_url}}"))

  cask <- .homebrew_cask_for_dependency(dependency$name)
  can_offer_brew_install <- !is.null(cask) &&
    identical(Sys.info()[["sysname"]], "Darwin") &&
    nzchar(Sys.which("brew")) &&
    interactive()

  if (!can_offer_brew_install) {
    cli::cli_alert_info(
      "No automatic install available for this platform -- use the link above."
    )
    return(invisible(NULL))
  }

  install_cmd <- paste("brew install --cask", cask)
  proceed <- isTRUE(tryCatch(
    utils::askYesNo(sprintf(
      "Homebrew found on this machine -- attempt `%s` now?", install_cmd
    )),
    error = function(e) FALSE
  ))
  if (!proceed) {
    return(invisible(NULL))
  }

  cli::cli_alert_info("Running: {install_cmd}")
  status <- tryCatch(system(install_cmd), error = function(e) NA_integer_)
  if (identical(status, 0L)) {
    cli::cli_alert_success(
      "{dependency$display_name} installed -- re-run your deckifyr command."
    )
  } else {
    cli::cli_alert_danger(paste0(
      "Install failed, or this machine has no network access to ",
      "Homebrew's servers -- install {dependency$display_name} ",
      "manually: {.url ", dependency$install_url, "}"
    ))
  }
  invisible(NULL)
}
