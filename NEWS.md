# deckifyr

# deckifyr (development version)

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
