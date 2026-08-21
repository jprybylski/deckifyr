# Rasterizes a saveRDS()-serialized flextable object to a transparent PNG.
# Invoked by deckifyr.renderers.flextable.render_flextable_png as:
#   Rscript --vanilla render_flextable.R <input.rds> <output.png> <dpi>
#
# Exits with status 2 (not R's default of 1 for an uncaught stop())
# specifically when the flextable package itself is missing, so the
# Python caller can raise a distinct MissingDependencyError instead of a
# generic render-failure message.

args <- commandArgs(trailingOnly = TRUE)
input_path <- args[[1]]
output_path <- args[[2]]
res <- as.numeric(args[[3]])

if (!requireNamespace("flextable", quietly = TRUE)) {
  cat("flextable package not installed\n", file = stderr())
  quit(status = 2, save = "no")
}

ft <- readRDS(input_path)
if (!inherits(ft, "flextable")) {
  stop(
    sprintf(
      "%s does not contain a flextable object (got class %s)",
      input_path, paste(class(ft), collapse = "/")
    ),
    call. = FALSE
  )
}

flextable::save_as_image(ft, path = output_path, res = res)
