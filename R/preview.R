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
#' @inheritParams deck_build
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
deck_preview <- function(presentation,
                         rscript_bin = NULL, quarto_bin = NULL, soffice_bin = NULL,
                         trusted_binaries_only = FALSE, allow_outside_project = FALSE) {
  args <- c("preview", presentation, .trust_args(
    rscript_bin, quarto_bin, soffice_bin, trusted_binaries_only, allow_outside_project
  ))
  .run_deckifyr_cli(args)
}
