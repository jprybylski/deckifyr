# Offline mode and pre-provisioned Python environments (issue #93).
#
# Nothing in deckifyr reaches the network unless the caller asks it to. The
# places it otherwise could are: `uv run` re-locking/syncing a stale project
# (and downloading a Python), pyro installing uv or the project's dependency
# group, and `init --from-repo` cloning a repository. Offline mode closes the
# first two; the Python engine refuses the third. `python_env` goes further
# and runs an environment that already exists, with no uv at all. Mirrors
# quartifyr's offline mode (see ../quartifyr/R/offline.R) so the two packages
# behave alike.

.truthy_env <- function(name) {
  tolower(trimws(Sys.getenv(name))) %in% c("1", "true", "yes", "on")
}

# TRUE when deckifyr should assume no network: `options(deckifyr.offline =
# TRUE)`, `DECKIFYR_OFFLINE=1`, or uv's own `UV_OFFLINE=1` (which uv itself
# honours, so a user who already set it gets consistent behaviour).
.offline_mode <- function() {
  isTRUE(getOption("deckifyr.offline")) ||
    .truthy_env("DECKIFYR_OFFLINE") ||
    .truthy_env("UV_OFFLINE")
}

# The environment variables offline mode sets on uv and on the deckifyr CLI
# (`DECKIFYR_OFFLINE` is what makes the Python side refuse `--from-repo`
# however it was reached). `provisioning = TRUE` leaves out UV_NO_INDEX:
# syncing a fresh environment from uv's cache needs the index *names* to
# resolve, only the network must be off (UV_OFFLINE), whereas a plain
# `uv run --no-sync` never resolves anything.
.offline_env_vars <- function(provisioning = FALSE) {
  if (!.offline_mode()) {
    return(character(0))
  }
  vars <- c(UV_OFFLINE = "1", DECKIFYR_OFFLINE = "1")
  if (!provisioning) {
    vars <- c(vars, UV_NO_INDEX = "1", UV_PYTHON_DOWNLOADS = "never")
  }
  vars
}

# Evaluates `code` with the offline variables set in this R process, then puts
# every one back as it was. They have to be set here rather than passed down:
# pyro::run_python_script() builds its subprocess environment as "current"
# plus its own variables, so the process environment is the only channel.
.with_offline_env <- function(code, provisioning = FALSE) {
  vars <- .offline_env_vars(provisioning)
  if (length(vars) == 0) {
    return(code)
  }
  old <- Sys.getenv(names(vars), unset = NA_character_)
  on.exit({
    unset <- names(old)[is.na(old)]
    if (length(unset) > 0) Sys.unsetenv(unset)
    kept <- old[!is.na(old)]
    if (length(kept) > 0) do.call(Sys.setenv, as.list(kept))
  })
  do.call(Sys.setenv, as.list(vars))
  code
}

# `uv run -m deckifyr`'s leading arguments. Offline adds --no-sync so a stale
# lock is used as it is instead of being re-locked against the index.
.uv_run_args <- function() {
  c("run", if (.offline_mode()) "--no-sync", "-m", "deckifyr")
}

# Signals an error of class `deckifyr_offline_failure` naming the step that
# needed the network and how to provide it locally. `how` may have several
# elements, one bullet each.
.abort_offline <- function(step, resource, how, env = parent.frame()) {
  cli::cli_abort(
    c(
      "x" = paste0("Cannot ", step, " without network access."),
      "!" = paste0("It needs ", resource, "."),
      stats::setNames(how, rep("i", length(how)))
    ),
    class = "deckifyr_offline_failure",
    call = NULL,
    .envir = env
  )
}

# A hint appended to a failed call's message when offline mode is on, since a
# stale lock or empty uv cache fails with uv's own wording, not ours.
.offline_hint <- function() {
  if (!.offline_mode()) {
    return("")
  }
  paste0(
    "\n  offline mode is on (--no-sync, no index, no Python downloads); if uv ",
    "reported a missing package or interpreter, provision the project's ",
    "environment while you have network access, or point ",
    "options(deckifyr.python_env = ...) at an existing environment."
  )
}

# ---- python_env: run an existing environment, no uv ------------------------

# `options(deckifyr.python_env)`, else `DECKIFYR_PYTHON_ENV`, else NULL.
.configured_python_env <- function(python_env = NULL) {
  env <- python_env
  if (is.null(env) || !nzchar(env)) {
    env <- getOption("deckifyr.python_env")
  }
  if (is.null(env) || !nzchar(env)) {
    env <- Sys.getenv("DECKIFYR_PYTHON_ENV")
  }
  if (is.null(env) || !nzchar(env)) {
    return(NULL)
  }
  env
}

# Makes a path absolute without resolving symlinks. That matters for a venv's
# `bin/python`, usually a symlink to the base interpreter: Python finds its
# `pyvenv.cfg` (hence its site-packages) from the path it was *invoked* as, so
# normalizePath(), which follows symlinks, would run the base interpreter and
# make every module in the venv look missing.
.absolute_path <- function(path, dir = getwd()) {
  path <- path.expand(path)
  if (grepl("^(/|[A-Za-z]:[/\\\\])", path)) path else file.path(dir, path)
}

# The interpreter inside an environment directory: a venv itself, or a project
# directory that holds a `.venv`.
.python_exe <- function(env) {
  env <- .absolute_path(env)
  candidates <- c(
    file.path(env, "bin", "python"),
    file.path(env, "Scripts", "python.exe"),
    file.path(env, ".venv", "bin", "python"),
    file.path(env, ".venv", "Scripts", "python.exe")
  )
  found <- candidates[file.exists(candidates)]
  if (length(found) == 0) {
    cli::cli_abort(
      c(
        "x" = "No Python interpreter found in the configured Python environment {.path {env}}.",
        "i" = paste(
          "Expected {.path {candidates[1]}} (or {.path {candidates[2]}}), or the same under",
          "{.file .venv/} if this is a project directory."
        )
      ),
      class = "deckifyr_python_env_invalid",
      call = NULL
    )
  }
  found[[1]]
}

# What the engine imports on every run, and the PyPI package behind each.
.required_python_modules <- c(
  pptx = "python-pptx", pydantic = "pydantic", yaml = "pyyaml", PIL = "pillow"
)

# PYTHONPATH for running the bundled engine (inst/python) with an interpreter
# that doesn't have deckifyr installed, keeping whatever is already on it.
.python_env_vars <- function(python_src) {
  existing <- Sys.getenv("PYTHONPATH")
  c(
    "current",
    PYTHONPATH = if (nzchar(existing)) {
      paste(python_src, existing, sep = .Platform$path.sep)
    } else {
      python_src
    }
  )
}

# Checks that `env` provides every module the engine needs, naming what is
# missing, and returns the interpreter path. Verified, never modified.
.verify_python_env <- function(env, modules = .required_python_modules) {
  python <- .python_exe(env)
  probe <- paste(
    "import importlib.util",
    sprintf("mods = [%s]", paste0("'", names(modules), "'", collapse = ", ")),
    "print(','.join(m for m in mods if importlib.util.find_spec(m) is None))",
    sep = "\n"
  )
  res <- processx::run(python, c("-c", probe), error_on_status = FALSE)
  if (!isTRUE(res$status == 0)) {
    cli::cli_abort(
      c(
        "x" = "The Python interpreter {.path {python}} could not be run.",
        "i" = "Underlying error: {trimws(res$stderr)}"
      ),
      class = "deckifyr_python_env_invalid",
      call = NULL
    )
  }
  missing <- Filter(nzchar, strsplit(trimws(res$stdout), ",", fixed = TRUE)[[1]])
  if (length(missing) > 0) {
    packages <- unname(modules[missing])
    cli::cli_abort(
      c(
        "x" = "The Python environment {.path {env}} is missing required module{?s}: {.val {missing}}.",
        "i" = paste(
          "Install {.val {packages}} into it, for example",
          "{.code pip install --no-index --find-links <wheel-dir> {packages}}."
        )
      ),
      class = "deckifyr_python_env_invalid",
      call = NULL
    )
  }
  python
}

# Runs the deckifyr CLI in `python_env` through processx. Same contract as
# pyro::run_python_script() as far as .run_deckifyr_cli() is concerned: the
# process's stderr reaches `stderr_callback` while it runs, and a non-zero exit
# is an error (the real diagnostic is recovered from that captured stderr).
.run_in_python_env <- function(python_env, cli_args, python_src, stderr_callback) {
  processx::run(
    command = .python_exe(python_env),
    args = c("-m", "deckifyr", cli_args),
    env = .python_env_vars(python_src),
    stderr_callback = stderr_callback,
    error_on_status = TRUE
  )
}
