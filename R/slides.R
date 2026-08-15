#' Turn after/before/index arguments into `deckifyr slide` CLI flags
#'
#' Shared by [deck_add_slide()] and [deck_move_slide()]. Validated here,
#' not just left to the Python side's own mutually-exclusive-group check,
#' per spec section 11.2's "Validate arguments in R when inexpensive" --
#' this is a cheap, purely local check.
#'
#' @noRd
.placement_args <- function(after, before, index) {
  given <- c(!is.null(after), !is.null(before), !is.null(index))
  if (sum(given) > 1) {
    stop("specify at most one of `after`, `before`, or `index`", call. = FALSE)
  }
  if (!is.null(after)) {
    return(c("--after", after))
  }
  if (!is.null(before)) {
    return(c("--before", before))
  }
  if (!is.null(index)) {
    return(c("--index", as.character(as.integer(index))))
  }
  character(0)
}

#' List the slides in a presentation.yaml
#'
#' Prints a compact cli-formatted summary (id, layout, element count,
#' whether it carries speaker notes) and returns the same data as a list
#' of R lists, one per slide, in slide order.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param quiet Suppress the cli summary; the return value is
#'   unaffected. Default `FALSE`.
#' @return A list of slide summaries (invisibly): each has `id`,
#'   `layout`, `element_count`, `has_notes`.
#' @examples
#' \dontrun{
#' presentation <- system.file(
#'   "examples", "minimal-deck", "presentation.yaml",
#'   package = "deckifyr"
#' )
#' deck_list_slides(presentation)
#' }
#' @export
deck_list_slides <- function(presentation, quiet = FALSE) {
  result <- .run_deckifyr_cli(c("slide", "list", presentation))
  slides <- result$slides

  if (!isTRUE(quiet)) {
    n <- length(slides)
    cli::cli_h3(sprintf(
      "%d slide%s in %s", n, if (n == 1) "" else "s", presentation
    ))
    for (slide in slides) {
      layout_label <- if (is.null(slide$layout)) "none" else slide$layout
      notes_label <- if (isTRUE(slide$has_notes)) ", notes" else ""
      element_word <- if (identical(slide$element_count, 1L)) "element" else "elements"
      cli::cli_li(
        "{.field {slide$id}} (layout: {layout_label}, {slide$element_count} {element_word}{notes_label})"
      )
    }
  }

  invisible(slides)
}

#' Add a new slide to a presentation.yaml
#'
#' Validates the edited `presentation.yaml` (including, when `layout` is
#' set, that it names a real entry in the project's `layouts.yaml`)
#' before writing -- see [deck_set_config()]'s own docstring for the same
#' validate-before-write guarantee.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param id The new slide's unique id.
#' @param layout The layout name to use, or `NULL` (default) for a
#'   freeform slide (`layout: null`).
#' @param notes Speaker notes text, or `NULL` (default) for none.
#' @param elements A (typically named, keyed by element id) list to use
#'   as the slide's `elements` block, or `NULL` (default) to add none
#'   yet. Encoded as JSON en route to the CLI, so nested boxes/styles are
#'   written exactly as given -- a named list becomes a JSON object
#'   (matching a layout-driven slide's `elements: {title: ..., ...}`
#'   form), an unnamed list becomes a JSON array (matching a freeform
#'   slide's `elements: [{id: ..., ...}, ...]` form).
#' @param after,before,index At most one of these controls placement:
#'   immediately `after`/`before` an existing slide id, or at a 0-based
#'   `index`. Default (all `NULL`) appends the slide at the end.
#' @return The CLI result (invisibly).
#' @examples
#' \dontrun{
#' # Copy the bundled example into a scratch directory first -- slide
#' # commands write to `presentation` in place.
#' project_dir <- file.path(tempdir(), "my-deck")
#' dir.create(project_dir)
#' file.copy(
#'   list.files(
#'     system.file("examples", "minimal-deck", package = "deckifyr"),
#'     full.names = TRUE
#'   ),
#'   project_dir
#' )
#' presentation <- file.path(project_dir, "presentation.yaml")
#' deck_add_slide(presentation, id = "new-slide", layout = "blank")
#' }
#' @export
deck_add_slide <- function(presentation, id, layout = NULL, notes = NULL,
                            elements = NULL, after = NULL, before = NULL,
                            index = NULL) {
  args <- c("slide", "add", presentation, "--id", id)
  if (!is.null(layout)) {
    args <- c(args, "--layout", layout)
  }
  if (!is.null(notes)) {
    args <- c(args, "--notes", notes)
  }
  if (!is.null(elements)) {
    args <- c(args, "--elements-json", jsonlite::toJSON(elements, auto_unbox = TRUE))
  }
  args <- c(args, .placement_args(after, before, index))

  result <- .run_deckifyr_cli(args)
  cli::cli_alert_success("Added slide {.field {id}} to {.file {presentation}}")
  invisible(result)
}

#' Remove a slide from a presentation.yaml
#'
#' @param presentation Path to `presentation.yaml`.
#' @param id The slide's id.
#' @return The CLI result (invisibly).
#' @examples
#' \dontrun{
#' # See deck_add_slide()'s example for setting up a scratch project_dir.
#' presentation <- file.path(project_dir, "presentation.yaml")
#' deck_remove_slide(presentation, id = "new-slide")
#' }
#' @export
deck_remove_slide <- function(presentation, id) {
  result <- .run_deckifyr_cli(c("slide", "remove", presentation, id))
  cli::cli_alert_success("Removed slide {.field {id}} from {.file {presentation}}")
  invisible(result)
}

#' Update an existing slide's layout, notes, or elements
#'
#' Only the arguments you pass are changed; anything else on the slide is
#' left as-is. `layout: null` (freeform) and "no notes" are both
#' meaningful, valid values in their own right (spec section 7.6) -- so
#' `NULL` can't double as this function's own "leave alone" default the
#' way it usually would in R. Pass `NA` instead to explicitly clear
#' `layout`/`notes`; `NULL` (the default) leaves that field untouched.
#'
#' @param presentation Path to `presentation.yaml`.
#' @param id The slide's id.
#' @param layout New layout name, `NA` to clear it (freeform), or `NULL`
#'   (default) to leave it unchanged.
#' @param notes New speaker notes text, `NA` to remove any notes, or
#'   `NULL` (default) to leave them unchanged.
#' @param elements A list to replace the slide's `elements` block with
#'   (same JSON encoding as [deck_add_slide()]'s `elements`), or `NULL`
#'   (default) to leave it unchanged.
#' @return The CLI result (invisibly).
#' @examples
#' \dontrun{
#' # See deck_add_slide()'s example for setting up a scratch project_dir.
#' presentation <- file.path(project_dir, "presentation.yaml")
#' deck_update_slide(presentation, id = "new-slide", notes = "Remember to mention Q3.")
#' }
#' @export
deck_update_slide <- function(presentation, id, layout = NULL, notes = NULL,
                               elements = NULL) {
  args <- c("slide", "update", presentation, id)

  if (identical(layout, NA)) {
    args <- c(args, "--no-layout")
  } else if (!is.null(layout)) {
    args <- c(args, "--layout", layout)
  }

  if (identical(notes, NA)) {
    args <- c(args, "--clear-notes")
  } else if (!is.null(notes)) {
    args <- c(args, "--notes", notes)
  }

  if (!is.null(elements)) {
    args <- c(args, "--elements-json", jsonlite::toJSON(elements, auto_unbox = TRUE))
  }

  result <- .run_deckifyr_cli(args)
  cli::cli_alert_success("Updated slide {.field {id}} in {.file {presentation}}")
  invisible(result)
}

#' Reorder a slide in a presentation.yaml
#'
#' @param presentation Path to `presentation.yaml`.
#' @param id The slide's id.
#' @param after,before,index At most one of these controls the new
#'   position: immediately `after`/`before` another slide's id, or a
#'   0-based `index`. `after`/`before` naming `id` itself is an error
#'   (there's no other copy of the slide to be relative to).
#' @return The CLI result (invisibly).
#' @examples
#' \dontrun{
#' # See deck_add_slide()'s example for setting up a scratch project_dir.
#' presentation <- file.path(project_dir, "presentation.yaml")
#' deck_move_slide(presentation, id = "new-slide", index = 0)
#' }
#' @export
deck_move_slide <- function(presentation, id, after = NULL, before = NULL, index = NULL) {
  args <- c("slide", "move", presentation, id, .placement_args(after, before, index))
  result <- .run_deckifyr_cli(args)
  cli::cli_alert_success("Moved slide {.field {id}} in {.file {presentation}}")
  invisible(result)
}
