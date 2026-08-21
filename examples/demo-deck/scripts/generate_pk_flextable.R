#!/usr/bin/env Rscript
# Regenerates OUTPUTS/tables/pk-flextable-summary.rds -- a `flextable`
# object summarizing the same per-participant Theoph-derived PK data
# OUTPUTS/tables/pk-summary.csv already contains (issue #57), styled via
# flextable's own formatting API (a merged top header spanning the value
# columns, a highlighted/bolded row) to make the "rich per-cell
# formatting a native PowerPoint table can't represent" point real
# rather than cosmetic -- this is what a `.rds` reportifyr table
# artifact means in this project's convention: an R object produced via
# `format_flextable()`-style styling, not a plain data.frame.
#
# Run from the repo root: Rscript examples/demo-deck/scripts/generate_pk_flextable.R

library(flextable)

pk <- read.csv("examples/demo-deck/OUTPUTS/tables/pk-summary.csv", check.names = FALSE)

value_cols <- c("Weight (kg)", "Dose (mg/kg)", "Cmax (mg/L)", "Tmax (hr)")
summary_df <- data.frame(
  Statistic = c("Mean", "Median", "Min", "Max"),
  check.names = FALSE
)
for (col in value_cols) {
  summary_df[[col]] <- round(
    c(mean(pk[[col]]), median(pk[[col]]), min(pk[[col]]), max(pk[[col]])), 2
  )
}

ft <- flextable(summary_df)
ft <- set_caption(ft, "Theophylline PK Summary Statistics (n = 12 participants)")
ft <- add_header_row(ft, values = c("", "Population Summary"), colwidths = c(1, length(value_cols)))
ft <- align(ft, align = "center", part = "all")
ft <- bold(ft, part = "header")
ft <- bg(ft, bg = "#2C5F8A", part = "header")
ft <- color(ft, color = "white", part = "header")
ft <- bg(ft, i = ~ Statistic == "Mean", bg = "#DCE9F5", part = "body")
ft <- bold(ft, i = ~ Statistic == "Mean", part = "body")
ft <- autofit(ft)

saveRDS(ft, "examples/demo-deck/OUTPUTS/tables/pk-flextable-summary.rds")
cat("wrote examples/demo-deck/OUTPUTS/tables/pk-flextable-summary.rds\n")
