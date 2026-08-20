#' Export deckifyr's bundled coding-agent skill files
#'
#' Copies the package's bundled coding-agent skill files (Claude
#' Skills-format `SKILL.md`s, issue #50) into `directory`: one skill for
#' authoring `design.yaml`/`layouts.yaml` (org-level Style/Layout
#' configuration), and one for authoring `presentation.yaml` (a deck's
#' own slide content). Each lands under its own
#' `<directory>/<skill-name>/SKILL.md` subdirectory, since a `SKILL.md`
#' file's name is fixed by the Skills convention -- point `directory` at
#' `.claude/skills` for Claude Code to auto-discover them, or anywhere
#' else for a different coding agent/tool, or just to inspect the
#' content.
#'
#' @param directory Target directory. Defaults to the current directory.
#' @param force Overwrite an existing `SKILL.md` at the destination.
#'   Default `FALSE`.
#' @return A list describing the created files (invisibly).
#' @examples
#' \dontrun{
#' deck_export_skills(".claude/skills")
#' }
#' @export
deck_export_skills <- function(directory = ".", force = FALSE) {
  args <- c("skills", directory)
  if (isTRUE(force)) {
    args <- c(args, "--force")
  }
  invisible(.run_deckifyr_cli(args))
}
