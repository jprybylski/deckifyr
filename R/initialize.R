#' Initialize a new deckifyr project
#'
#' Provisions a project-local Python environment via pyro (writing a
#' `deckifyr` dependency group to the calling project's `pyproject.toml`,
#' per deckifyr-specification.md section 5.2) and scaffolds
#' `design.yaml`/`layouts.yaml`/`presentation.yaml` into `directory` --
#' from the bundled minimal example by default, or from a template
#' source (issue #34) when `from_dir`/`from_repo` is given.
#'
#' A template source is either "flat" (a directory with its own
#' `presentation.yaml`, whose `design`/`layouts` files are duplicated
#' under their original names and paired with a freshly generated,
#' empty-slide `presentation.yaml` -- the "duplicate a prior project"
#' case) or "typed" (a directory with a `templates/` subdirectory, each
#' holding its own named flat template -- select one with `type`; its
#' `presentation.yaml` is copied verbatim as a real minimal starter,
#' not emptied).
#'
#' @section Offline mode:
#' Offline mode is on when `options(deckifyr.offline = TRUE)`,
#' `DECKIFYR_OFFLINE=1` or uv's own `UV_OFFLINE=1` is set, and nothing in
#' deckifyr then reaches the network:
#'
#' * `deck_validate()`, `deck_build()`, `deck_preview()`, `deck_serve()` and
#'   the other wrappers run `uv run --no-sync`, with `UV_OFFLINE`,
#'   `UV_NO_INDEX` and `UV_PYTHON_DOWNLOADS=never` set, so a stale lock is
#'   used as it is instead of being re-locked and synced against the index.
#' * `from_repo` is refused (clone the repository yourself while you have
#'   access and pass the checkout as `from_dir`), here and in
#'   `deckifyr init --from-repo`.
#' * Provisioning the environment here runs with `UV_OFFLINE=1` (uv's cache
#'   only) and stops with a message, rather than letting pyro download it,
#'   when `uv` is not installed.
#'
#' Alternatively, `python_env` skips uv altogether.
#'
#' @section Python packages:
#' The `deckifyr` dependency group written to `pyproject.toml` includes the
#' packages behind the `web` extra (`fastapi`, `uvicorn`, for `deck_serve()`)
#' and the `preview` extra (`pymupdf`, for `deck_preview()` and
#' `build.previews`), so both work after a plain initialization. Parquet table
#' sources need `pyarrow`, which is not added; add it to the group if you use
#' them. An existing group is merged, so re-running this adds what is missing.
#'
#' @param directory Target directory. Defaults to the current directory.
#' @param force Overwrite existing files in `directory`. Default `FALSE`.
#' @param from_dir Use a local directory as the template source instead
#'   of the bundled minimal example. Mutually exclusive with `from_repo`.
#' @param from_repo Fetch a git repo as the template source:
#'   `"[host/]owner/repo[/subdir][@ref]"` shorthand (host defaults to
#'   github.com -- an explicit host is how GitHub Enterprise is
#'   supported) or a full URL. Requires `git` on PATH. Mutually
#'   exclusive with `from_dir`.
#' @param ref Branch/tag/SHA to check out. Only valid with `from_repo`;
#'   overrides any `@ref` embedded in its shorthand.
#' @param subdir Subdirectory of the resolved repo to use as the
#'   template source. Only valid with `from_repo`; overrides any
#'   subdirectory embedded in its shorthand.
#' @param type Template name under a source's `templates/<name>/`
#'   structure. Only valid alongside `from_dir`/`from_repo`.
#' @param python_env Path to an existing Python environment (a venv, or a
#'   project directory holding a `.venv`) with `python-pptx`, `pydantic`,
#'   `pyyaml` and `pillow`. It is verified and used as it is: pyro and uv are
#'   skipped, nothing is installed and `pyproject.toml` is not touched.
#'   Defaults to `getOption("deckifyr.python_env")`, then the
#'   `DECKIFYR_PYTHON_ENV` environment variable. Every deckifyr function
#'   (`deck_build()`, `deck_serve()`, ...) uses the same setting, so set the
#'   option in the project's `.Rprofile` as well.
#' @return A list describing the created files (invisibly).
#' @examples
#' \dontrun{
#' # Scaffold a new project into a scratch directory (this mutates the
#' # calling project's pyproject.toml and provisions a Python/uv
#' # environment -- run it somewhere disposable, not the current project).
#' project_dir <- file.path(tempdir(), "my-deck")
#' initialize_deck_project(project_dir)
#'
#' # Scaffold from an org-standard design/layouts repo instead, pinned
#' # to a tag, selecting the "quarterly-review" template type.
#' initialize_deck_project(
#'   project_dir,
#'   from_repo = "acme-org/deck-templates@v2",
#'   type = "quarterly-review"
#' )
#' }
#' @export
initialize_deck_project <- function(directory = ".", force = FALSE,
                                     from_dir = NULL, from_repo = NULL,
                                     ref = NULL, subdir = NULL, type = NULL,
                                     python_env = getOption("deckifyr.python_env")) {
  offline <- .offline_mode()
  if (offline && !is.null(from_repo)) {
    .abort_offline(
      step = "fetch the template repository for {.arg from_repo}",
      resource = "{.val {from_repo}} (a git clone from the network)",
      how = c(
        "Clone it while you have access, then pass that checkout as {.arg from_dir}.",
        "Or run {.fn initialize_deck_project} without {.arg from_repo} and copy the template files in yourself."
      )
    )
  }

  python_env <- .configured_python_env(python_env)
  if (!is.null(python_env)) {
    # A pre-provisioned environment replaces pyro/uv entirely: nothing in the
    # project is touched and nothing can reach for the network. The option is
    # set for the rest of this call so the `init` CLI below runs in it too.
    .verify_python_env(python_env)
    old_options <- options(deckifyr.python_env = python_env)
    on.exit(options(old_options), add = TRUE)
    snippet <- sprintf("options(deckifyr.python_env = \"%s\")", python_env)
    cli::cli_inform(c(
      "v" = "Using the Python environment {.path {python_env}}; pyro/uv provisioning skipped.",
      "i" = "Set {.code {snippet}} in this project's {.file .Rprofile} so the other deckifyr functions use it as well."
    ))
  } else {
    .provision_python_with_pyro(offline)
  }

  args <- c("init", directory)
  if (!is.null(from_dir)) {
    args <- c(args, "--from-dir", from_dir)
  }
  if (!is.null(from_repo)) {
    args <- c(args, "--from-repo", from_repo)
  }
  if (!is.null(ref)) {
    args <- c(args, "--ref", ref)
  }
  if (!is.null(subdir)) {
    args <- c(args, "--subdir", subdir)
  }
  if (!is.null(type)) {
    args <- c(args, "--type", type)
  }
  if (isTRUE(force)) {
    args <- c(args, "--force")
  }
  invisible(.run_deckifyr_cli(args))
}

# Dependency versions are not pinned yet -- spec section 5.2 shows exact pins
# as an illustrative `==<pin>` placeholder; real pins are one of version 1's
# open decisions (spec section 21). The lower bounds are pyproject.toml's own.
# Besides the core engine, the group carries what the `web` extra
# (deck_serve()) and the `preview` extra (deck_preview(), build.previews) need
# at runtime, so those work straight after initialization (issue #93).
.deckifyr_group_deps <- function() {
  c(
    "python-pptx", "pydantic", "pyyaml", "pillow",
    "fastapi", "uvicorn",
    "pymupdf"
  )
}

# Writes the "deckifyr" dependency group and has pyro create the environment.
#
# Offline: pyro's uv_setup.sh only reaches for the network when `uv` is
# missing (it curl-installs it into ~/.local/bin) or when its version differs
# from the requested one, and `uv lock`/`uv sync` honour UV_OFFLINE=1. So an
# offline run sets that variable (cache only, hence not UV_NO_INDEX, see
# .offline_env_vars()) and refuses up front when uv isn't installed.
.provision_python_with_pyro <- function(offline) {
  if (offline && is.null(pyro::get_uv_path(quiet = TRUE))) {
    .abort_offline(
      step = "provision the Python environment",
      resource = "{.code uv}, which isn't installed (pyro would download it from github.com/astral-sh/uv and install it into {.path ~/.local/bin})",
      how = c(
        "Install uv yourself and put it on {.envvar PATH} (a single static binary; any recent version works).",
        "Or skip uv altogether: pass {.arg python_env} (or set {.code options(deckifyr.python_env = ...)}) to an existing environment with python-pptx, pydantic, pyyaml and pillow."
      )
    )
  }

  pyro::write_group_to_pyproject(name = "deckifyr", deps = .deckifyr_group_deps())
  .with_offline_env(pyro::initialize_python(groups = "deckifyr"), provisioning = TRUE)
  invisible(NULL)
}
