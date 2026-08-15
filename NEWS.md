# deckifyr

# deckifyr 0.1.2

## Added

* `design.yaml` `colors:` entries may now be derived from another color
  token via a simple HSL-space transform (`lighten`/`darken`/`saturate`/
  `desaturate`, or `mix` toward a second color) instead of always being a
  hand-picked literal hex value, per issue #11. Derivations may chain to
  arbitrary depth; a circular chain is a build-time error.
* A new vignette, "YAML Configuration Reference"
  (`vignette("config-schema")`), documents the `design.yaml`/
  `layouts.yaml`/`presentation.yaml` schema field by field, closing
  issue #16.

## Documentation

* Every exported R function now has a runnable (`\dontrun{}`-wrapped)
  `@examples` block, closing issue #15.

# deckifyr 0.1.1

## Added

* `deckifyr get`/`set` CLI subcommands and R's `deck_get_config()`/
  `deck_set_config()`: read or write one value in a `design.yaml`/
  `layouts.yaml`/`presentation.yaml` file by dotted path (e.g.
  `colors.primary`, `slides[0].notes`), validated against the right
  schema (and, for a slide's `layout`, cross-checked against
  `layouts.yaml`) before anything is written to disk.
* `deckifyr slide list/add/remove/update/move` and R's
  `deck_list_slides()`/`deck_add_slide()`/`deck_remove_slide()`/
  `deck_update_slide()`/`deck_move_slide()`: id-keyed slide management
  for `presentation.yaml`'s own `slides` list, per issue #10.

# deckifyr 0.1.0

## Added

* Core schema layer: `deckifyr.schema.units` (length parsing), `deckifyr.schema.merge`
  (deep-merge precedence), and the `design`/`layouts`/`presentation` pydantic
  document models, each requiring an explicit `deckifyr:` version field.
* Pass 1 plan/shell expansion (`deckifyr.plan`) for `text`, `markdown`, `image`,
  `shape`, `group`, `table`, and `reportifyr` elements, plus document furniture
  (background image, status marker, branding, page number) and per-slide
  speaker notes.
* Pass 2 PowerPoint composition (`deckifyr.pptx`) for the same element set,
  including native, fully-editable PPTX tables with optional `design.yaml`
  `table_styles` chrome (fill/border), grouped shapes, and reportifyr-derived
  footers written either beneath an element or into the slide's speaker notes.
* The reportifyr magic-string resolver (`deckifyr.resolvers.ReportifyrResolver`):
  resolves `{rpfy}:name.ext` references and their metadata sidecars into
  deckifyr's own plain `Source`/`Notes`/`Abbreviations` footer format.
* CLI `init`/`validate`/`build`/`schema` (real); `preview`/`inspect`/`serve`
  parse arguments but raise `NotImplementedFeatureError` today.
* R facade (`R/*.R`) delegating to the bundled Python CLI via `pyro`, tested
  against a live install (`tests/testthat/test-wiring.R`).
* `examples/demo-deck/`, a four-slide, repo-only demo resolving a real
  `reportifyr`-produced figure, a `table` element, a multi-zone layout,
  rotation, and `z_index`.

## Not yet implemented

* `deckifyr.renderers` (Quarto integration, Phase 2) and `deckifyr.web`
  (Phase 3) are intentionally empty.
* Reference-PPTX support is descoped, not deferred: composition always
  starts from `python-pptx`'s own bundled default template.
