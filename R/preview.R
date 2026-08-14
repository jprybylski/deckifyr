#' Render slide previews
#'
#' Delegates to `deckifyr preview` in the bundled Python engine.
#' **Not implemented yet** -- the preview renderer is spec section 18's
#' Phase 3 work; this currently always errors with a clear "not
#' implemented" message.
#'
#' @param presentation Path to `presentation.yaml`.
#' @return A parsed list from the CLI's JSON output.
#' @export
deck_preview <- function(presentation) {
  .run_deckifyr_cli(c("preview", presentation))
}
