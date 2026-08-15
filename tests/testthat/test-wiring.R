# Proves the R -> pyro -> bundled-Python bridge actually works, not just
# that the R function signatures exist. Skips (rather than fails) when
# the toolchain isn't present, matching quartifyr's convention (see its
# CLAUDE.md) of skip-if-unavailable for tests that need a real R + uv +
# venv stack rather than mocking pyro.

skip_if_not_installed("pyro")

repo_root <- test_path("..", "..")
minimal_deck <- file.path(repo_root, "inst", "examples", "minimal-deck")
demo_deck <- file.path(repo_root, "examples", "demo-deck")

# pyro::get_venv_uv_paths() looks for an already-provisioned .venv/ at
# the project root -- it does not create one itself, and it errors
# (not a skip-able condition on its own) if none exists. `uv sync
# --extra dev` (see CONTRIBUTING.md/ci.yml) provisions it; this is the
# same .venv/ the tests/python suite uses, not a separate pyro-specific
# one, confirmed locally: pyro is satisfied by a plain `uv run`-created
# venv with no `pyro::initialize_python()` call ever having run.
skip_if_not(
  dir.exists(file.path(repo_root, ".venv")),
  "repo .venv/ not provisioned (run `uv sync --extra dev` first)"
)

test_that("deck_validate() reports a valid project as valid", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  result <- deck_validate(file.path(minimal_deck, "presentation.yaml"))
  expect_true(result$valid)
  expect_equal(result$slide_count, 2)
})

test_that("deck_build() writes a real .pptx and manifest", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  # Build from a scratch copy rather than in place, so this test doesn't
  # leave a build/ directory inside the repo's bundled example (the same
  # fixture `deckifyr init`/`initialize_deck_project()` scaffolds from).
  project_dir <- file.path(tempdir(), "deckifyr-wiring-build")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)
  file.copy(
    file.path(minimal_deck, c("design.yaml", "layouts.yaml", "presentation.yaml")),
    project_dir
  )

  result <- deck_build(file.path(project_dir, "presentation.yaml"))
  expect_true(file.exists(result$output))
  expect_true(file.exists(result$manifest))
  expect_equal(result$slide_count, 2)
})

test_that("deck_build() builds the richer demo-deck example end to end", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")
  # examples/demo-deck's pk-interpretation slide (spec section 8.1,
  # issue #3) has two real `type: quarto` elements -- this whole deck
  # now requires the external `quarto` binary to build, same skip
  # convention tests/python/test_demo_deck.py uses on the Python side.
  skip_if_not(nzchar(Sys.which("quarto")), "quarto not on PATH")

  # examples/demo-deck (see its README.md) exercises a multi-zone layout,
  # a real reportifyr-produced image, rotation, z_index, and two real
  # quarto fragments (an equation and an R-executed narrative) together
  # -- inst/examples/minimal-deck deliberately stays text/markdown-only.
  project_dir <- file.path(tempdir(), "deckifyr-wiring-demo-deck")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)
  for (entry in c(
    "design.yaml", "layouts.yaml", "presentation.yaml", "standard_footnotes.yaml",
    "OUTPUTS", "assets", "fragments"
  )) {
    file.copy(file.path(demo_deck, entry), project_dir, recursive = TRUE)
  }

  result <- deck_build(file.path(project_dir, "presentation.yaml"))
  expect_true(file.exists(result$output))
  expect_true(file.exists(result$manifest))
  expect_equal(result$slide_count, 5)
})

test_that("deck_get_config()/deck_set_config()/slide editors round-trip a real file", {
  skip_if_not(nzchar(Sys.which("uv")), "uv not on PATH")

  # Edits a scratch copy, never the repo's own bundled fixture -- the
  # same reasoning the deck_build() test above gives for copying first.
  project_dir <- file.path(tempdir(), "deckifyr-wiring-editing")
  unlink(project_dir, recursive = TRUE)
  dir.create(project_dir)
  file.copy(
    file.path(minimal_deck, c("design.yaml", "layouts.yaml", "presentation.yaml")),
    project_dir
  )
  presentation_path <- file.path(project_dir, "presentation.yaml")
  design_path <- file.path(project_dir, "design.yaml")

  expect_equal(deck_get_config(design_path, "colors.primary"), "#2457A6")
  deck_set_config(design_path, "colors.primary", "#123456")
  expect_equal(deck_get_config(design_path, "colors.primary"), "#123456")

  slides_before <- deck_list_slides(presentation_path, quiet = TRUE)
  expect_equal(length(slides_before), 2)

  deck_add_slide(
    presentation_path,
    id = "wiring-slide", layout = "blank", notes = "added by a wiring test",
    after = "title"
  )
  slides_after_add <- deck_list_slides(presentation_path, quiet = TRUE)
  expect_equal(vapply(slides_after_add, `[[`, character(1), "id"), c("title", "wiring-slide", "content-slide"))

  deck_update_slide(presentation_path, "wiring-slide", notes = "updated notes")
  expect_equal(
    deck_get_config(presentation_path, "slides[1].notes"), "updated notes"
  )

  deck_move_slide(presentation_path, "wiring-slide", index = 0)
  slides_after_move <- deck_list_slides(presentation_path, quiet = TRUE)
  expect_equal(slides_after_move[[1]]$id, "wiring-slide")

  deck_remove_slide(presentation_path, "wiring-slide")
  slides_after_remove <- deck_list_slides(presentation_path, quiet = TRUE)
  expect_equal(vapply(slides_after_remove, `[[`, character(1), "id"), c("title", "content-slide"))

  # The edited files must still be a valid, buildable project.
  result <- deck_validate(presentation_path)
  expect_true(result$valid)
})
