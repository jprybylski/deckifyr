#' Build a presentation
#'
#' Delegates to `deckifyr build` in the bundled Python engine. **Not yet
#' functional end-to-end**: the PPTX compositor
#' (`deckifyr.pptx`, spec section 10) isn't implemented, so this
#' currently always errors with a clear "not implemented" message once
#' the input itself has been validated -- see spec section 18, Phase 1.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param strict Reject unitless geometry when `TRUE` (default).
#' @return A parsed list from the CLI's JSON output.
#' @export
deck_build <- function(presentation, strict = TRUE) {
  args <- c("build", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  .run_deckifyr_cli(args)
}
