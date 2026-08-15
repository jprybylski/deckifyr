#' Read a config value from a design/layouts/presentation YAML file
#'
#' Delegates to `deckifyr get` in the bundled Python engine, so the same
#' dotted-path syntax (`.` for mapping keys, `[N]` for 0-based list
#' indices, e.g. `"colors.primary"` or `"slides[0].notes"`) works
#' regardless of which of the three schemas (design/layouts/presentation)
#' `file` is.
#'
#' @param file Path to a `design.yaml`, `layouts.yaml`, or
#'   `presentation.yaml`.
#' @param path Dotted path into the document.
#' @return The value at `path`, as its native R type (list, character,
#'   numeric, logical, or `NULL`).
#' @export
deck_get_config <- function(file, path) {
  result <- .run_deckifyr_cli(c("get", file, path))
  result$value
}

#' Write a config value into a design/layouts/presentation YAML file
#'
#' `value` is parsed as JSON by default -- `"true"`/`"12"`/`"[1, 2]"`
#' become their native typed values -- so a plain word, hex color, or
#' font name (`"Arial"`, `"#2457A6"`) needs no quoting and is written as
#' a literal string. Use `as_string = TRUE` for the rare case a value
#' would otherwise parse as something other than a string (writing the
#' literal text `"true"` or `"null"`, for instance). The edited document
#' is validated against its schema -- and, for `presentation.yaml`, any
#' changed `slide.layout` is cross-checked against the project's
#' `layouts.yaml` -- *before* anything is written to `file`, so a bad
#' edit never corrupts it.
#'
#' @param file Path to a `design.yaml`, `layouts.yaml`, or
#'   `presentation.yaml`.
#' @param path Dotted path to write, same syntax as [deck_get_config()].
#' @param value The value to write.
#' @param as_string Treat `value` as a literal string rather than parsing
#'   it as JSON. Default `FALSE`.
#' @param type Which schema to validate the edited document against.
#'   `"auto"` (the default) detects it from the document's own top-level
#'   keys.
#' @return The parsed CLI result (invisibly).
#' @export
deck_set_config <- function(file, path, value,
                             as_string = FALSE,
                             type = c("auto", "design", "layouts", "presentation")) {
  type <- match.arg(type)
  args <- c("set", file, path, as.character(value))
  if (isTRUE(as_string)) {
    args <- c(args, "--string")
  }
  args <- c(args, "--type", type)

  result <- .run_deckifyr_cli(args)
  cli::cli_alert_success("Set {.field {path}} in {.file {file}}")
  invisible(result)
}
