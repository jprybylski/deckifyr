#' Build a presentation
#'
#' Delegates to `deckifyr build` in the bundled Python engine: plans
#' (`deckifyr.plan`) and composes (`deckifyr.pptx`, spec section 10) a
#' `.pptx` and manifest for `text`/`markdown`/`image`/`shape`/`group`/
#' `table`/`reportifyr`/`quarto` elements. A `quarto` element requires
#' the external `quarto` binary on `PATH` (spec section 8.1, issue #3);
#' every other element type needs nothing beyond this package's own
#' Python dependencies.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param strict Reject unitless geometry when `TRUE` (default).
#' @return A parsed list from the CLI's JSON output, including `output`
#'   (the written `.pptx` path), `manifest` (the manifest path, or `NULL`
#'   if `presentation.yaml`'s `build.manifest` is unset), and
#'   `slide_count`.
#' @export
deck_build <- function(presentation, strict = TRUE) {
  args <- c("build", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  .run_deckifyr_cli(args)
}
