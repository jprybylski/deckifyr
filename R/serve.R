#' Inspect a presentation or .pptx
#'
#' Delegates to `deckifyr inspect` in the bundled Python engine.
#' **Not implemented yet** -- see spec section 18, Phase 1/4.
#'
#' @param target Path to a `presentation.yaml` or a built `.pptx`.
#' @return A parsed list from the CLI's JSON output.
#' @export
deck_inspect <- function(target) {
  .run_deckifyr_cli(c("inspect", target))
}

#' Print a document type's JSON Schema
#'
#' Delegates to `deckifyr schema` in the bundled Python engine. This one
#' is fully functional today: it dumps the pydantic-generated JSON
#' Schema for `design`, `layouts`, or `presentation`.
#'
#' @param document One of `"design"`, `"layouts"`, or `"presentation"`.
#' @return A parsed list representing the document type's JSON Schema.
#' @export
deck_schema <- function(document = c("design", "layouts", "presentation")) {
  document <- match.arg(document)
  .run_deckifyr_cli(c("schema", document))
}

#' Run the local web application
#'
#' Delegates to `deckifyr serve` in the bundled Python engine.
#' **Not implemented yet** -- the optional web application is spec
#' section 12's Phase 3 work, deliberately deferred until the CLI and
#' schema stabilize (spec section 20, warning 5).
#'
#' @param host Host to bind. Default `"127.0.0.1"`.
#' @param port Port to bind. Default `8000`.
#' @return A parsed list from the CLI's JSON output.
#' @export
deck_serve <- function(host = "127.0.0.1", port = 8000) {
  .run_deckifyr_cli(c("serve", "--host", host, "--port", as.character(port)))
}
