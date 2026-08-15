# deckifyr

# deckifyr 0.2.0

## Added

* `deckifyr serve`/`deck_serve()`/`deck_stop_server()`: a local web
  editor over the same Python engine `deck_build()` already uses.
  `deck_serve()` launches a FastAPI backend as a background process
  (`processx`) and opens it in the RStudio/Positron Viewer pane or your
  default browser, the same `shiny::runApp()`-style single-project
  model; `deck_stop_server()` shuts it down.
* The FastAPI backend (`deckifyr.web.app`, requires the new optional
  `deckifyr[web]` extra) exposes config get/put
  (`GET`/`PUT /api/config/{doc}`) with schema validation before any
  write, on-canvas element editing (`PATCH /api/slides/{slide}
  /elements/{element}`), resolved-plan/validate endpoints
  (`GET /api/plan`, `POST /api/validate`), background build jobs
  (`POST /api/build`, `GET /api/jobs/{id}`) that shell out to a real
  `deckifyr build` subprocess rather than composing in-request, and
  artifact download by a server-issued key
  (`GET /api/jobs/{id}/artifacts/{key}`).
* A new React/TypeScript + react-konva web editor (built assets bundled
  under `inst/python/deckifyr/web/static/`): drag/resize/rotate
  `text`/`markdown`/`image` elements on a slide canvas, edit slide text
  inline, edit `design`/`layouts`/`presentation.yaml` as raw JSON, and
  trigger/download a build. `shape`/`group`/`table`/`reportifyr`/
  `quarto` elements and image pixels render as placeholders only --
  see the new "Using the web editor" article for the full, honest scope
  of what's built versus not yet.
* `deckifyr/projectio.py`: the project-loading/config-validation/YAML
  read-write mechanism shared by the CLI's `get`/`set`/`slide`
  commands and the new web backend, extracted out of `cli.py` so
  neither reimplements the other.

## Documentation

* New vignette, "Using the web editor" (`vignette("web-app")`), covering
  `deck_serve()`/`deck_stop_server()` and today's editor scope.
* README's status callout and architecture diagram, and CLAUDE.md's
  status table, no longer describe the web application as unbuilt --
  both now reflect that `deckifyr serve` is real.

# deckifyr 0.1.3

## Added

* `deckifyr preview`/`deck_preview()` render each slide to a standalone
  PNG via LibreOffice + PyMuPDF (requires the external `soffice` binary
  on `PATH`); `build.previews: true` also renders them as part of an
  ordinary `deckifyr build`. New `build.preview` config block
  (`binary`/`dpi`/`timeout_seconds`) tunes the render.
* `deckifyr inspect`/`deck_inspect()` reports a `presentation.yaml`'s
  resolved slide plan, or a built `.pptx`'s real shape structure (plus
  its sibling manifest, if one exists) -- target type is detected from
  the file extension.
* A missing external binary (LibreOffice for `preview`, Quarto for a
  `quarto` element) now fails with a structured `E_MISSING_DEPENDENCY`
  error naming where to get it; from R, `.run_deckifyr_cli()` also
  prints install guidance, and on macOS with Homebrew already on `PATH`
  offers to install it for you.

## Documentation

* README's status summary, architecture diagram, component table, and
  quick-start examples updated to match what's actually implemented
  (config/slide editing, `preview`, `inspect`).

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
