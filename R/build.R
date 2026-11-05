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
#' @param rscript_bin,quarto_bin,soffice_bin Run this executable instead of
#'   whatever `presentation.yaml`'s `build.reportifyr.flextable.binary`,
#'   `build.quarto.binary` or `build.preview.binary` says (`NULL`, the
#'   default, keeps the project file's own setting). For a launcher that
#'   treats project files as untrusted user data (`deckifyr.policy`).
#' @param trusted_binaries_only If `TRUE`, a project file that names a
#'   non-default `binary` (and no override was given for it) fails with
#'   `E_UNTRUSTED_BINARY` before anything runs, and `design.base`,
#'   `layouts`, `build.output`, `build.manifest` and `build.reportifyr`'s
#'   paths must stay inside the project (`E_PATH_OUTSIDE_PROJECT`).
#'   Default `FALSE`: existing projects behave exactly as before.
#' @param allow_outside_project With `trusted_binaries_only = TRUE`, let those
#'   paths resolve outside the project (e.g. a shared organization design).
#'   Default `FALSE`.
#' @return A parsed list from the CLI's JSON output:
#'   \describe{
#'     \item{`output`}{The written `.pptx` path.}
#'     \item{`manifest`}{The manifest path, or `NULL` if
#'       `presentation.yaml`'s `build.manifest` is unset.}
#'     \item{`slide_count`}{Number of slides composed.}
#'     \item{`warning_count`}{Number of non-fatal build warnings --
#'       includes a skipped preview render when `build.previews: true`
#'       and LibreOffice isn't installed.}
#'     \item{`warnings`}{The warnings themselves, a list with one entry
#'       per warning: `code` (a stable identifier such as
#'       `"W_MISSING_SIDECAR"`), `message`, and the `slide`/`element` ids
#'       it came from (`NULL` for a build-level warning). Present
#'       whether or not a manifest is written.}
#'     \item{`previews`}{Per-slide preview PNG paths, only non-empty when
#'       `build.previews: true` actually rendered them.}
#'     \item{`preview_pdf`}{The intermediate PDF LibreOffice produced
#'       alongside those PNGs, or `NULL` if previews weren't rendered.}
#'     \item{`artifacts`}{A list of every file the build produced
#'       (`kind`, `path`, `sha256`), so provenance can be recorded
#'       without re-hashing.}
#'     \item{`status`, `result_version`}{`"ok"` and the version of the
#'       result schema (currently `1`); new keys may be added within a
#'       version, so treat unknown entries as ignorable.}
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
deck_build <- function(presentation, strict = TRUE,
                       rscript_bin = NULL, quarto_bin = NULL, soffice_bin = NULL,
                       trusted_binaries_only = FALSE, allow_outside_project = FALSE) {
  args <- c("build", presentation)
  if (!isTRUE(strict)) {
    args <- c(args, "--warn-only")
  }
  args <- c(args, .trust_args(
    rscript_bin, quarto_bin, soffice_bin, trusted_binaries_only, allow_outside_project
  ))
  .run_deckifyr_cli(args)
}
