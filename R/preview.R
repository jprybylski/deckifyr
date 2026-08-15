#' Render slide previews
#'
#' Delegates to `deckifyr preview` in the bundled Python engine: builds
#' the project (regardless of its own `build.previews` setting) and
#' rasterizes each slide to a standalone PNG via LibreOffice + PyMuPDF,
#' alongside the ordinary `.pptx`/manifest output. Requires the external
#' `soffice` binary (LibreOffice) on `PATH`.
#'
#' @param presentation Path to `presentation.yaml`.
#' @return A parsed list from the CLI's JSON output, including `output`
#'   (the built `.pptx` path) and `previews` (one PNG path per slide).
#' @examples
#' \dontrun{
#' deck_preview("presentation.yaml")
#' }
#' @export
deck_preview <- function(presentation) {
  .run_deckifyr_cli(c("preview", presentation))
}
