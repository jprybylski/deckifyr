# deckifyr

# deckifyr (development version)

## Added

* `shape`/`table`/`reportifyr`/`quarto` elements can now be dragged,
  resized, and rotated on the web editor's canvas (issue #54), the same
  placeholder-box interaction `image` elements already had -- no
  backend changes were needed, since the PATCH endpoint and schema
  already supported positioning any element type generically. `group`
  elements are intentionally still a static placeholder: a group's
  on-slide position is derived entirely from its own children's boxes
  at build time, not its own `box` field, so making it draggable needs
  a separate, larger fix (tracked in issue #55).

# deckifyr 0.3.0

## Added

* Layouts editor mode in the web editor (issue #30): `SlideList`'s
  "Slides" / "Layouts" toggle swaps the entire numbered list between
  `presentation.yaml`'s slides and `layouts.yaml`'s layouts, with real
  add/remove/rename layout CRUD. Every `layouts.yaml` must now define a
  `blank` layout, which can't itself be removed -- it's the fallback any
  slide using a removed layout falls back to. Removing an in-use layout
  previews which slides would be reassigned before you confirm, and the
  server rejects the removal outright (no partial write) if reassignment
  would leave a slide unbuildable.
* Element add/remove for both slides and layout zones (issue #31): a new
  `ElementList` sidebar (replacing the old always-on `ElementInspector`
  slot and the standalone furniture bar) lists every element as a
  collapsed row you expand to edit; `reportifyr`/`quarto` elements get a
  real file picker scoped to your project instead of a hand-typed path.
* Slide add/remove/duplicate, and color swatches next to token pickers
  in the config editor (issues #23, #27).
* Build tab improvements (issue #32): the output-path field is now a
  real single-level directory browser instead of free text; a "Render
  slide previews" checkbox turns on `build.previews` and now keeps the
  intermediate PDF alongside the PNGs for an ordinary `deckifyr build`,
  not just `deckifyr preview`; and a shared preview gallery (PNG
  thumbnails, collapsed-until-requested PDF) is used by both the Build
  and Preview sections. The previews checkbox is disabled with a clear
  warning when LibreOffice isn't available, and a `build.previews: true`
  build with no LibreOffice now downgrades to a build warning instead of
  losing the `.pptx` output entirely.
* `deckifyr skills [DIRECTORY]` / `deck_export_skills()` (issue #50):
  exports two bundled Claude Skills-format `SKILL.md` files
  (`deckifyr-org-config` for `design.yaml`/`layouts.yaml`,
  `deckifyr-presentation` for `presentation.yaml`) to a directory of
  your choice, for use with Claude Code or any other coding agent that
  reads `SKILL.md` files.
* `deckifyr init --from-dir <path>` / `--from-repo <spec>` (issue #34):
  scaffold a new project from an existing local directory or git repo
  instead of only the bundled minimal example. `--from-repo` accepts a
  `[host/]owner/repo[/subdir][@ref]` shorthand as well as a full git
  URL. A "typed" source (a `templates/` directory of design/layouts/
  presentation trios, selected via `--type`) is copied as-is; a "flat"
  source copies just its `design.yaml`/`layouts.yaml` and generates a
  fresh, empty `presentation.yaml` pointing at them.
* Static JSON Schema files for `design`/`layouts`/`presentation`
  (`inst/python/deckifyr/schemas/*.schema.json`, issue #49), so IDEs
  like VS Code's YAML extension can validate against a real file via a
  `yaml-language-server` `$schema` comment instead of shelling out to
  `deckifyr schema`.
* A third, Playwright-based end-to-end test tier for the web editor,
  alongside the existing pytest and vitest suites.

## Changed

* `status_indicator` is a single-select again: the corner/watermark
  split introduced in 0.2.1 (`watermark_overlay`) turned out to have a
  confusing Add/Remove-vs-checkbox story with no real benefit, so a
  corner placement and the full-page watermark once again share the
  same `status_indicator` selection.

## Fixed

* A `quarto` element rendered as a PNG now composites with a
  transparent background instead of opaque white (issue #9).
* The "Deck Options" status-indicator dropdown now stays in sync after
  the Furniture panel's own Add/Remove changes `status_indicator`
  server-side, instead of showing stale state until a manual refresh.
* Optional scalar fields in the schema-driven config form (an author
  name, a table style's color, a corner's rotation, ...) no longer
  render as a cut-off ~260px-tall sliver.

# deckifyr 0.2.1

## Added

* Deferred-save editing in the web editor (issue #24): `deckifyr serve`
  now holds one in-memory working copy of `design`/`layouts`/
  `presentation.yaml` for the life of the process instead of writing
  straight to disk on every mutation. Edits stay in memory until an
  explicit **Save** (or the new `build.autosave: true`), and a new
  **Discard** reloads from disk -- this is what makes it safe to try
  new features against a real project (e.g. `examples/demo-deck`)
  without dirtying tracked files.
* The full-page watermark overlay is now its own independently-
  activatable furniture element (`presentation.watermark_overlay`)
  rather than being tangled with `status_indicator`'s corner-or-
  watermark single-select, so a corner status indicator and a
  full-page watermark can render at the same time.
* `deckifyr serve` now warns (on stderr, and as a banner in the app
  itself via `GET /api/health`'s new `frontend_warning` field) when a
  dev checkout's built `web/static/` bundle is older than `web/src/` --
  a browser hard-refresh alone doesn't catch this, since the server is
  still serving genuinely stale, uncompiled JS.

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
