#' Render slide previews
#'
#' Delegates to `deckifyr preview` in the bundled Python engine: builds
#' the project (regardless of its own `build.previews` setting) and
#' rasterizes each slide to a standalone PNG via LibreOffice + PyMuPDF,
#' alongside the ordinary `.pptx`/manifest output. Requires the external
#' `soffice` binary (LibreOffice) on `PATH` -- unlike [deck_build()]'s
#' own opportunistic `build.previews: true` (which just skips previews
#' with a warning when LibreOffice is missing), rendering previews is
#' this function's entire purpose, so a missing `soffice` is always a
#' hard failure here.
#'
#' @param presentation Path to `presentation.yaml`.
#' @return A parsed list from the CLI's JSON output:
#'   \describe{
#'     \item{`output`}{The built `.pptx` path.}
#'     \item{`slide_count`}{Number of slides composed.}
#'     \item{`previews`}{One PNG path per rendered slide.}
#'     \item{`preview_pdf`}{The intermediate PDF LibreOffice produced
#'       alongside those PNGs.}
#'   }
#' @examples
#' \dontrun{
#' deck_preview("presentation.yaml")
#' }
#' @export
deck_preview <- function(presentation) {
  .run_deckifyr_cli(c("preview", presentation))
}
