# deckifyr

# deckifyr (development version)

## Fixed

* The web editor's **+ Add slide** with a layout that has a required zone
  (`title-content`'s `title`) no longer leaves an uneditable slide that blanks
  the editor on reload (issue #101). `GET /api/plan` now plans leniently for the
  editor: an empty layout zone shows as a dashed placeholder ("title (required)
  -- empty"), a slide that cannot be planned is reported on its own (`error`)
  without taking the other slides down, and the slide list flags the slide that
  needs attention. A text zone is filled from the inspector's new **Content**
  field (or by clicking it on the canvas), and a `slot` with **Fill...**, which
  keeps the layout's geometry (`inherit_box`). Patching a layout zone the slide
  has not overridden yet creates the override instead of returning 404. The
  new slide is selected after adding. `build` and `validate` are unchanged: a
  required element with no content still fails them.

# deckifyr 0.3.7

## Fixed

* A `table` element whose CSV has an empty header or data cell builds (issue
  #96). It failed at build time with `E_INTERNAL: IndexError: tuple index out
  of range`, because python-pptx creates no run for an empty string and the
  cell's font was applied to `runs[0]`. The cell stays empty in the PPTX and
  now carries an empty, styled run, so text typed into it later in PowerPoint
  keeps the table's font. Non-empty cells are unchanged.

# deckifyr 0.3.6

## Added

* Offline mode for the R wrappers (issue #93). With `options(deckifyr.offline
  = TRUE)`, `DECKIFYR_OFFLINE=1` or uv's own `UV_OFFLINE=1`, `deck_validate()`,
  `deck_build()`, `deck_preview()`, `deck_serve()` and the other wrappers run
  `uv run --no-sync` with `UV_OFFLINE`, `UV_NO_INDEX` and
  `UV_PYTHON_DOWNLOADS=never` set, so a stale lock is used as it is instead of
  being re-locked and synced against the index (which also downloaded a Python
  when none was cached). `init --from-repo` -- `initialize_deck_project(from_repo
  =)` and `deckifyr init --from-repo` -- is refused with a message pointing at
  `--from-dir`, since it needs a `git clone`. Provisioning in
  `initialize_deck_project()` runs with `UV_OFFLINE=1` and stops, instead of
  letting pyro download it, when `uv` is not installed. Online behaviour is
  unchanged.
* `python_env` (`initialize_deck_project(python_env =)`,
  `options(deckifyr.python_env)` or `DECKIFYR_PYTHON_ENV`): run an existing
  Python environment (a venv, or a project directory with a `.venv`) directly,
  with no pyro or uv at all. It is verified for `python-pptx`, `pydantic`,
  `pyyaml` and `pillow` and never modified; every wrapper, including
  `deck_serve()`, uses it.

## Changed

* The `deckifyr` dependency group `initialize_deck_project()` writes to
  `pyproject.toml` now includes the packages behind the `web` and `preview`
  extras (`fastapi`, `uvicorn`, `pymupdf`), so `deck_serve()` and previews work
  straight after initialization instead of failing on a missing module. An
  existing group is merged, so re-running it adds them. The "extra is not
  installed" errors name `initialize_deck_project()` when run from R.

## Fixed

* Project files that start with a UTF-8 byte order mark load (issue #94).
  Windows PowerShell 5.1 (`Set-Content -Encoding utf8`) and older Notepad write
  one, and it became part of the first key, so `design.yaml`, `layouts.yaml` or
  `presentation.yaml` failed with `E_SCHEMA_VALIDATION` (`deckifyr: Field
  required` / `Extra inputs are not permitted`). Project YAML and JSON, a table
  CSV (a BOM no longer lands in the first column name), `standard_footnotes.yaml`,
  reportifyr metadata sidecars and Quarto fragments are now read as UTF-8 with
  an optional BOM. They were also read with the locale's default encoding, which
  on Windows is cp1252, so non-ASCII text in a UTF-8 file was mis-decoded; and
  `deckifyr set`/`slide` wrote with that same default. Both are explicit UTF-8
  now (written files stay BOM-free). Files without a BOM are unaffected.

# deckifyr 0.3.5

## Added

* `deckifyr serve` now guards its API against other pages open in the same
  browser (issue #88). Only `127.0.0.1`/`localhost`/`[::1]` on the served
  port, the bound `--host` and any `--allowed-host` (repeatable) are
  accepted as `Host` -- anything else gets `421`, which stops DNS-rebinding
  access. A state-changing request (`POST`/`PUT`/`PATCH`/`DELETE`) marked
  `Sec-Fetch-Site: cross-site` or `same-site`, or carrying an `Origin` that
  is not allowed, gets `403`; before this a cross-site form `POST` to
  `/api/build`, `/api/discard` or `/api/shutdown` ran the handler. Curl, the
  R facade, CI, the editor itself and the R Viewer pane are unaffected. A
  supervising launcher can also set `--api-token-env VAR`: every `/api/*`
  request except `GET /api/health` must then send the secret from that
  environment variable as `X-Deckifyr-Api-Token` (read from the environment,
  never argv; static assets stay open).
* A launcher can stop a project file from choosing executables or paths
  (issue #89). `--rscript-bin`/`--quarto-bin`/`--soffice-bin` (or
  `DECKIFYR_RSCRIPT_BIN`/`..._QUARTO_BIN`/`..._SOFFICE_BIN`) run the
  launcher's own executables instead of the project file's.
  `--trusted-binaries-only` (`DECKIFYR_TRUSTED_BINARIES_ONLY`) rejects a
  project whose `build.*.binary` differs from the default name with
  `E_UNTRUSTED_BINARY` before anything runs, and requires `design.base`,
  `layouts`, `build.output`, `build.manifest` and `build.reportifyr` paths to
  resolve (symlinks followed) inside the project, else
  `E_PATH_OUTSIDE_PROJECT`; `--allow-outside-project` relaxes the paths for a
  shared organization design. It applies to `validate`, `build`, `preview`,
  `inspect`, `serve` (including the editor's config `PUT` and saves) and, via
  the environment, `get`/`set`/`slide`. All of it is off by default.
  `deck_build()`, `deck_validate()`, `deck_preview()`, `deck_inspect()` and
  `deck_serve()` take the same options.
* `validate --warn-only` (and `build --warn-only`) report each unitless
  length it coerces to EMUs as a `W_UNITLESS_LENGTH` warning, instead of
  accepting it silently (issue #91).
* `GET /api/health` reports `project_loaded` and `project_error`
  (`{code, message}`), so one probe tells a supervisor both that the server is
  up and whether the project is usable. It is still `200` either way.
* The global `--debug` flag (or `DECKIFYR_DEBUG=1`) adds a `traceback` to the
  error payload of an unexpected failure.

## Changed

* A release is now immutable (issue #91): pushing to `main` without bumping
  `VERSION` no longer re-tags the published version or re-uploads its assets
  (the workflow emits a notice instead). A consumer that pins `deckifyr X.Y.Z`
  plus the SHA-256 of its wheel or `SHA256SUMS` can rely on both naming fixed
  bytes; to ship a change, bump `VERSION`. Enabling GitHub's "immutable
  releases" repository setting enforces the same thing server-side.
* `build` writes its `.pptx`, previews and manifest atomically (issue #90).
  Everything is built in a private `.deckifyr-staging-*` directory next to the
  output and only promoted once every step succeeded, manifest last, so a
  failed or killed build leaves the previous build's files untouched and a
  manifest on disk always matches the files it names. A full preview render
  replaces that deck's previous preview files, so a preview set can no longer
  mix two builds. Leftovers from a killed build are swept at the next build.
* The published `--json` result schemas now allow extra keys (as the docs
  always said adding a key is not a breaking change) and carry a versioned
  `$id` (issue #91).

## Fixed

* Any exception that is not a `deckifyr` error -- for example a
  `PermissionError` because the output `.pptx` is open in PowerPoint -- now
  produces the `--json` error payload on stderr (`E_IO` for an OS error,
  `E_INTERNAL` otherwise) instead of a bare traceback with no JSON (issue #90).
* The process-tree and orphan tests now run on Windows too (issue #91).

# deckifyr 0.3.4

## Added

* `deckifyr serve` can run as a managed child of a launcher and behind a
  reverse proxy (issues #82, #83). The editor now uses page-relative
  URLs, so it works mounted under a path prefix (e.g.
  `/apps/deckifyr/`) behind a prefix-stripping proxy with no
  configuration; `--root-path` supports a proxy that does not strip the
  prefix. `--launcher workspace` gives the no-project screen
  workspace-appropriate guidance and implies the new
  `--no-frontend-rebuild` (never run `npm` at startup). `GET /api/health`
  now reports `dirty` and `active_jobs`, and `POST /api/shutdown`
  (`{"if_dirty": "refuse"|"save", "active_jobs": "refuse"|"cancel"}`)
  stops the server in an orderly way: a refusal is a `409` with no side
  effects, `save` writes edits first, and the process exits 0. A plain
  SIGTERM/SIGINT with unsaved edits now writes a warning to stderr
  instead of dropping them silently.
* Background build/preview jobs are bounded and cancellable (issue #84):
  a job-level timeout (`deckifyr serve --job-timeout`, 600 s by default)
  reports `E_TIMEOUT`, `POST /api/jobs/{id}/cancel` and a Cancel button
  in the Build tab stop a running job, and both kill the whole process
  tree (new `deckifyr._proc`), so no LibreOffice is left behind.
  Preview rendering also uses a private LibreOffice profile per call, so
  it no longer collides with an open LibreOffice or with a concurrent
  preview.
  Timed-out Quarto and flextable (`Rscript`) renders now kill their whole
  process tree too, instead of leaving pandoc/R children running.
* The CLI's `--json` output is a versioned contract (issue #85): every
  success and error payload carries `result_version` (`1`); `build` and
  `preview` return the full `warnings` list (`code`, `message`, `slide`,
  `element`) whether or not a manifest is written, plus an `artifacts`
  list of `{kind, path, sha256}`; `validate`/`build`/`preview`/error
  payloads have published JSON Schemas under `schemas/results/`. All
  existing keys are unchanged.
* Each release now attaches a versioned Python wheel and sdist plus a
  `SHA256SUMS` file covering them and the R tarball (issue #86). The
  Python package version is read from `VERSION`, so the wheel, a build
  manifest's `deckifyr_version` and the release tag always agree.

## Fixed

* `deckifyr init` (without `--from-dir`/`--from-repo`) now works from an
  installed wheel: the bundled minimal example was not packaged, so it
  only worked from a repo checkout.
* Installing the Python package no longer prints a `SyntaxWarning` from
  `deckifyr.renderers.quarto`.

# deckifyr 0.3.3

## Changed

* The web editor's Config tab form is redesigned. Documents are split
  into sections (a left rail, one pane at a time) instead of one long
  scroll box; fields use styled inputs, switches and segmented controls,
  collapsible cards, and show a per-field hint taken from the schema.
  Colors are a swatch plus a text field with the document's own color
  tokens as pick-able chips, lengths are a number plus a unit with
  arrow-key stepping, and unions that used to fall back to raw JSON
  (`colors:` entries that are literal or derived, `fill` as a color or a
  gradient, `elements` as named or a list) are a segmented switch between
  their forms. The three JSON Schema files (`deckifyr schema`) now carry
  a `description` on every property and an `x-deckifyr-widget`
  annotation on color/length strings; no document field changed.

# deckifyr 0.3.2

## Added

* Reportifyr `.rds` table artifacts (R `flextable` objects, produced via
  `format_flextable()`) now render as pictures instead of crashing the
  build, and the web editor's reportifyr artifact picker correctly
  routes `.csv`/`.parquet` picks to native tables instead of always
  building a `reportifyr` element (issue #57). New
  `deckifyr.renderers.flextable` shells out to `Rscript`/`flextable::
  save_as_image()` to rasterize a `.rds` artifact to a transparent PNG,
  composed exactly like any other `reportifyr` figure, footer included.

# deckifyr 0.3.1

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
