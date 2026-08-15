#' Initialize a new deckifyr project
#'
#' Provisions a project-local Python environment via pyro (writing a
#' `deckifyr` dependency group to the calling project's `pyproject.toml`,
#' per deckifyr-specification.md section 5.2) and scaffolds
#' `design.yaml`/`layouts.yaml`/`presentation.yaml` from the bundled
#' minimal example into `directory`.
#'
#' @param directory Target directory. Defaults to the current directory.
#' @param force Overwrite existing files in `directory`. Default `FALSE`.
#' @return A list describing the created files (invisibly).
#' @examples
#' \dontrun{
#' # Scaffold a new project into a scratch directory (this mutates the
#' # calling project's pyproject.toml and provisions a Python/uv
#' # environment -- run it somewhere disposable, not the current project).
#' project_dir <- file.path(tempdir(), "my-deck")
#' initialize_deck_project(project_dir)
#' }
#' @export
initialize_deck_project <- function(directory = ".", force = FALSE) {
  # Dependency versions are not pinned yet -- spec section 5.2 shows
  # exact pins as an illustrative `==<pin>` placeholder; real pins are
  # one of version 1's open decisions (spec section 21).
  pyro::write_group_to_pyproject(
    name = "deckifyr",
    deps = c("python-pptx", "pydantic", "pyyaml", "pillow")
  )
  pyro::initialize_python(groups = "deckifyr")

  args <- c("init", directory)
  if (isTRUE(force)) {
    args <- c(args, "--force")
  }
  invisible(.run_deckifyr_cli(args))
}
