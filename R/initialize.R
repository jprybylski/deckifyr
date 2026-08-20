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
                                     ref = NULL, subdir = NULL, type = NULL) {
  # Dependency versions are not pinned yet -- spec section 5.2 shows
  # exact pins as an illustrative `==<pin>` placeholder; real pins are
  # one of version 1's open decisions (spec section 21).
  pyro::write_group_to_pyproject(
    name = "deckifyr",
    deps = c("python-pptx", "pydantic", "pyyaml", "pillow")
  )
  pyro::initialize_python(groups = "deckifyr")

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
