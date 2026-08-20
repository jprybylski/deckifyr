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
#' `presentation.yaml`'s `build.previews: true` makes an ordinary build
#' also render a PNG per slide (plus the intermediate PDF LibreOffice
#' produces along the way) alongside the `.pptx` -- the same thing the
#' web editor's own "Render slide previews" checkbox controls (see
#' `vignette("web-app")`). Unlike [deck_preview()], a missing LibreOffice
#' here does not fail the build: it's an opportunistic, secondary output
#' riding along on a build whose actual deliverable (the `.pptx`) has
#' already been written to disk by the time previews would render, so a
#' missing `soffice` only adds one entry to the returned list's
#' `warning_count`/manifest `warnings` -- `output`/`manifest` are still
#' returned normally. [deck_preview()] has no such fallback: rendering
#' previews is its entire purpose, so a missing LibreOffice there is
#' always a hard failure.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param strict Reject unitless geometry when `TRUE` (default).
#' @return A parsed list from the CLI's JSON output:
#'   \describe{
#'     \item{`output`}{The written `.pptx` path.}
#'     \item{`manifest`}{The manifest path, or `NULL` if
#'       `presentation.yaml`'s `build.manifest` is unset.}
#'     \item{`slide_count`}{Number of slides composed.}
#'     \item{`warning_count`}{Number of non-fatal build warnings (the
#'       manifest itself carries their text) -- includes a skipped
#'       preview render when `build.previews: true` and LibreOffice
#'       isn't installed.}
#'     \item{`previews`}{Per-slide preview PNG paths, only non-empty when
#'       `build.previews: true` actually rendered them.}
#'     \item{`preview_pdf`}{The intermediate PDF LibreOffice produced
#'       alongside those PNGs, or `NULL` if previews weren't rendered.}
#'   }
#' @examples
#' \dontrun{
#' # Build the bundled minimal example project (requires a provisioned
#' # Python/uv/pyro toolchain -- see vignette("getting-started")).
#' presentation <- system.file(
#'   "examples", "minimal-deck", "presentation.yaml",
#'   package = "deckifyr"
#' )
#' result <- deck_build(presentation)
#' result$output
#' }
#' @export
deck_build <- function(presentation, strict = TRUE) {
  args <- c("build", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  .run_deckifyr_cli(args)
}
