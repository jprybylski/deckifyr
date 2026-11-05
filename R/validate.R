#' Validate a deckifyr project
#'
#' Loads and validates `presentation.yaml` plus its referenced
#' `design.yaml`/`layouts.yaml` (schema shape, layout references, and
#' element box unit strings). Does not merge layouts onto slides or
#' resolve content -- see `deckifyr.cli`'s module docstring in the
#' bundled Python source for what validation currently does and does not
#' cover.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param strict Reject unitless geometry when `TRUE` (default); `FALSE`
#'   is the `--warn-only` policy from spec section 11.1. Each unitless length
#'   it then accepts is reported in `$warnings` as `W_UNITLESS_LENGTH`.
#' @inheritParams deck_build
#' @return A parsed list from the CLI's JSON output, e.g. `$valid`,
#'   `$slide_count`, `$layout_count`.
#' @examples
#' \dontrun{
#' # Validate the bundled minimal example project (requires a provisioned
#' # Python/uv/pyro toolchain -- see vignette("getting-started")).
#' presentation <- system.file(
#'   "examples", "minimal-deck", "presentation.yaml",
#'   package = "deckifyr"
#' )
#' deck_validate(presentation)
#' }
#' @export
deck_validate <- function(presentation, strict = TRUE,
                          rscript_bin = NULL, quarto_bin = NULL, soffice_bin = NULL,
                          trusted_binaries_only = FALSE, allow_outside_project = FALSE) {
  args <- c("validate", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  args <- c(args, .trust_args(
    rscript_bin, quarto_bin, soffice_bin, trusted_binaries_only, allow_outside_project
  ))
  .run_deckifyr_cli(args)
}
