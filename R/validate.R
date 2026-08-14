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
#'   is the `--warn-only` policy from spec section 11.1.
#' @return A parsed list from the CLI's JSON output, e.g. `$valid`,
#'   `$slide_count`, `$layout_count`.
#' @export
deck_validate <- function(presentation, strict = TRUE) {
  args <- c("validate", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  .run_deckifyr_cli(args)
}
