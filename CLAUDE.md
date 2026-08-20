# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

deckifyr is a declarative, code-first presentation compiler: it generates
`.pptx` decks from version-controlled YAML (design tokens, logical
layouts, slide content -- three separate, versioned schemas) instead of
a hand-clicked PowerPoint template. It's a sibling project to
[`../quartifyr`](../quartifyr) in the same `fyr` ecosystem, inheriting
its reproducible, YAML-driven philosophy while targeting slides instead
of Word documents, and it's meant to support
[`reportifyr`](https://github.com/A2-ai/reportifyr) artifacts
(`{rpfy}:` magic strings) the same way quartifyr's shells do -- but as
its own independent repository, release cycle, and dependency graph,
not a subsystem bolted onto quartifyr.

**`deckifyr-specification.md`** at the repo root is the authoritative
design document (architecture, full schema reference, compilation
model, Reportifyr/Quarto integration, security model, phased delivery
plan). Everything below assumes you've skimmed it; this file covers
what's actually built versus still spec, and the non-obvious things
learned while building the scaffold.

### Current status: early scaffold, not the compiler yet

| Piece | Status |
| --- | --- |
| `deckifyr.schema.units` (length parsing, spec §7.3) | Real, tested |
| `deckifyr.schema.merge` (deep-merge precedence, spec §7.2) | Real, tested |
| `deckifyr.schema.{design,layouts,presentation}` (pydantic models, spec §7.4-7.7) | Real, tested |
| `deckifyr.plan` (Pass 1: plan and shell expansion, spec §6) | Real, tested -- `text`/`markdown`/`image`/`shape`/`group`/`table`/`reportifyr`/`quarto` elements, plus document furniture (spec §7.8) expansion and per-slide speaker notes |
| CLI `init`/`validate`/`build`/`preview`/`inspect`/`schema` (spec §11.1) | Real, tested |
| CLI `serve` | Argument parsing is real; raises `NotImplementedFeatureError` (exit code 4) -- Phase 3 |
| `deckifyr.editor` + CLI `get`/`set`/`slide` (config/slide editing, spec §11.1/§11.2, issue #10) | Real, tested |
| `deckifyr.renderers.preview` (slide preview rendering, spec §12/§18 Phase 3) | Real, tested against a live `soffice`/PyMuPDF install -- see this file's own "Preview rendering" section below |
| R facade (`R/*.R`) | Real, tested against a live pyro install |
| `deckifyr.pptx` (PowerPoint compositor, spec §10) | Real, tested for `text`/`markdown`/`image`/`shape`/`group`/`table`/`reportifyr`/`quarto` elements, `Slide.notes`, and reportifyr footers (§9.1) -- Phase 1 and Phase 2's Quarto slice (§18, issue #3) are done |
| `deckifyr.resolvers` concrete resolvers (spec §9.2) | `LocalFileResolver`, `InlineResolver`, `TableResolver` (CSV always, Parquet via the optional `pyarrow` extra), `ReportifyrResolver` (magic-string + metadata sidecar resolution, spec §9.1), and `QuartoResolver` (fragment execution, spec §9.2/§8.1) are real |
| `deckifyr.renderers.quarto` (Quarto integration, spec §8/§8.1, issue #3) | Real, tested against a live `quarto` install -- see this file's own "Quarto integration" section below |
| `deckifyr.web` (spec §12) | Real: FastAPI backend (`deckifyr.web.app`/`deckifyr.web.jobs`) + a built React/Konva frontend, CLI `serve`, R `deck_serve()`/`deck_stop_server()` -- see this file's own "Web application" section below |

Concretely: `deckifyr validate presentation.yaml` does real schema and
geometry validation today. `deckifyr build presentation.yaml` validates
the same way, then plans and composes a real `.pptx` + manifest for
projects that use `text`/`markdown`/`image`/`shape`/`group`/`table`/
`reportifyr`/`quarto` elements. `table` elements resolve their
`source` (a `.csv` or `.parquet` file, project-relative like an image's
`source`) to a native, fully-editable PowerPoint table -- first row is
always the header, mirroring `pandas`' own `header=0` default; `style`
on a `table` element still reuses an ordinary `text_styles` entry for
typography, applied uniformly to every cell (header cells are bold
regardless of the style). Chrome -- fill/border, the part `text_styles`
has no vocabulary for -- is a separate, optional `table_style` field
naming a `design.yaml` `table_styles` entry (`deckifyr.schema.design.
TableStyle`; `defaults.table_style` sets a project-wide fallback,
mirroring `defaults.footer_style`); unset on both the element and
`defaults` means every table keeps `python-pptx`'s bundled default
template look untouched, exactly as before this field existed. Fill
(`header_fill`/`body_fill`/`band_fill`/`header_text_color`) goes
through `python-pptx`'s public `cell.fill`/`run.font.color` API; border
(`border_color`/`border_width`) does not have a public API at all in
`python-pptx` (`CT_TableCellProperties` models fill/margin/anchor only,
not `a:lnL/lnR/lnT/lnB`) so `deckifyr.pptx.compose._set_cell_borders`
builds those elements directly via lxml -- confined to that one
function per spec §10.2's warning, the same pattern `_set_alt_text`
already uses, and it must run before that cell's `cell.fill.solid()`
touches the same `a:tcPr` since OOXML orders border children ahead of
the fill child and `python-pptx`'s own fill-insertion logic doesn't
know these undeclared siblings exist. `shape`'s autoshape kinds are a small
named subset of `MSO_SHAPE` (`deckifyr.schema.layouts.ShapeKind`), not
the full enum; `group` nests any supported element (including another
group) and composes via `python-pptx`'s `add_group_shape`, reparenting
already-placed child shapes rather than using a group-relative
coordinate system -- a group's children still use the same slide-
absolute geometry as everything else (spec §7.3). Document furniture
(§7.8, closing issue #1) is real: `design.yaml`'s `furniture` block
(background image, status marker, branding, page number) expands, once
per slide, into reserved `text`/`image` elements
(`__furniture_background`/`__furniture_status`/`__furniture_branding`/
`__furniture_page_number`) merged beneath the slide's own layout zones
using the same override/`remove` machinery those zones already use --
not a parallel code path, and no changes to `deckifyr.pptx.compose` at
all. Furniture paints behind ordinary content by default
(`z_index: -1000` for the background, `-10` for the other three).
`page_number.format` substitutes exactly `{page}`/`{total}` via
`str.format`; `branding.text` is a literal string with no placeholder
substitution (general `design.yaml` variable/expression support remains
an open question, spec §21). `furniture.status` is deckifyr's status-
indicator/watermark mechanism, redesigned from a single on/off marker
into a set of named *placements*: `deckifyr.schema.design.StatusFurniture`
has five optional `StatusIndicatorStyle | None` fields --
`watermark`, `corner_tr`, `corner_tl`, `corner_bl`, `corner_br` -- each
its own `box`/`style`/`rotation`/`z_index`, none of them "the" status
marker on their own. `presentation.yaml`'s top-level `status_indicator`
field (`deckifyr.schema.layouts.StatusIndicatorMode`, a `Literal` shared
by both schema modules to avoid duplicating the value set) picks exactly
one -- `"watermark"`, one of the four hyphenated `"corner-*"` values (a
plain YAML string has no identifier restriction, unlike
`StatusFurniture`'s own underscored field names, hence the spelling
mismatch), or `"none"`/unset (default, nothing shown) -- and
`presentation.yaml`'s own `watermark` field (`str | None`, any word, no
longer a bool) supplies the text, falling back to `metadata.status`
(`deckifyr.plan.expand_presentation`, computed once before the
per-slide `expand_slide` loop) when `watermark` itself is `None` -- the
expected common case, so a deck doesn't need the same word ("draft",
"demo", ...) typed into both `metadata.status` (already there for
descriptive purposes) and a separate `watermark` field. `deckifyr.plan
._furniture_layout` maps the hyphenated mode to the underscored field
via `_STATUS_INDICATOR_FIELDS`, looks up that `StatusIndicatorStyle` on
`design.furniture.status`, and raises `ContentValidationError` if
`None` (spec §20 warning 7 -- selecting a placement `design.yaml` never
configured must not silently render nothing). A `corner-*` placement
with no text from either source is simply skipped (no content, not
required, same as any other unfilled element); `status_indicator:
watermark` with *neither* `watermark` nor `metadata.status` set is
instead a schema-validation error -- `PresentationDocument`'s own
`model_validator(mode="after")`, since a full-page watermark with
nothing to say would be a large, silently empty rotated box, worth
failing over immediately rather than at build time. Turning free text
like `metadata.status: demo` into the conventional all-caps status/
watermark look ("DEMO") is a third new field, `TextStyle.text_transform`
(`none`/unset/`uppercase`/`lowercase`/`capitalize`) -- unlike `opacity`,
a plain `str.upper()`/`.lower()`/`.title()` in
`deckifyr.pptx.compose._apply_text_transform`, no OOXML gap to work
around, applied to each run's text right before `run.text` is set (so
markdown's own bold/italic markers are already stripped by the time it
runs, not accidentally transformed). Every status/watermark element also
gets a new, general `center`
field (`deckifyr.schema.layouts.Element.center`, default `False`,
inert everywhere else): `deckifyr.pptx.compose._add_text_shape` sets
`text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE` and
`paragraph.alignment = PP_ALIGN.CENTER` when it's set, which
`_furniture_layout` always does for `__furniture_status` regardless of
placement -- a short label/word reads correctly centered, and a large
rotated watermark reads distractingly off-center without it (this was
the actual visual bug that prompted the field: an uncentered "DRAFT"
sat visibly left-of-center once rotated). Vertical centering and
horizontal alignment were the same bool until issue #13 asked for them
independently: a corner placement (`corner_tr`/`corner_br`/`corner_tl`/
`corner_bl`) rotated to hug an edge still needs to stay vertically
centered *within its own box*, but centering it horizontally too just
leaves the text sitting in the middle of the rotated strip instead of
flush against the actual corner. `Element.align` (`Literal["left",
"center", "right"] | None`, default `None`) is the fix -- independent
of `center`, and only meaningful when set; `None` falls back to
`center`'s own original all-or-nothing behavior (`"center"` if
`center=True`, otherwise the compositor's ordinary left-aligned
default), so every pre-existing `center: true` usage (`watermark`,
still `align=None`) is unaffected. `_furniture_layout`'s own
`_STATUS_CORNER_ALIGN` sets it automatically from which corner field is
selected (`corner_tr`/`corner_br` -> `"right"`, `corner_tl`/`corner_bl`
-> `"left"`) -- not a `design.yaml`-authored field on
`StatusIndicatorStyle` itself, since it's determined entirely by which
edge the corner is on, not a per-placement style choice.
`deckifyr.pptx.compose._add_text_shape`'s `_TEXT_ALIGN` maps it to
`PP_ALIGN` and sets `paragraph.alignment` whenever it (or the
`center`-derived fallback) resolves to something, independent of the
`vertical_anchor = MIDDLE` line `center` alone still controls. Neither
`rotation` nor `align` is automatic or edge-aware within the engine
itself, though -- a `corner_*` placement that leaves `rotation` at its
`0` default renders as an ordinary upright label like any other element;
rotating a corner to hug an edge (and getting the box geometry right so
the rotated, aligned text actually lands flush against that edge rather
than off-slide or floating away from it) is a `design.yaml` authoring
choice, worked out in `examples/demo-deck/design.yaml`'s own
`corner_tr`/`corner_br` comments -- including why `corner_br`'s `box.y`
is deliberately declared well past the slide's own height (the box is a
virtual frame the rotation pivots around, not literal on-slide bounds,
so solving for where the *rotated* text lands took precedence over the
declared rectangle looking like it belongs on the slide). A placement's
own `rotation`
(0 by default, like every other element's own rotation) is what makes
the `watermark` placement diagonal rather than upright, and its `z_index`
(unset by default, so it paints behind content like every other
furniture item -- `_FURNITURE_OVERLAY_Z_INDEX`) is what opts it into
painting *on top* of ordinary content instead, the conventional
Word/Google-Docs watermark placement. Getting that on-top case to
actually read as a watermark (rather than a large diagonal label sitting
in front of everything, fully obscuring it) needed one more field:
`TextStyle.opacity` (spec §7.4, 0.0-1.0, `None` = fully opaque, every
other `text`/`markdown`/`table`/footer style unaffected). `python-pptx`
has no public API for run color alpha, so
`deckifyr.pptx.compose._apply_text_alpha` appends an `<a:alpha>` child
directly to the `<a:srgbClr>` element `run.font.color.rgb`'s own setter
already created -- must run after that setter, same ordering
requirement `_set_cell_borders` has with `cell.fill.solid()` -- verified
against a real `.pptx` reopened with `python-pptx` (the alpha child
round-tripped exactly). `examples/demo-deck/design.yaml`'s own
`watermark` `text_styles` entry uses a saturated `color: primary` with
`opacity: 0.28` doing the softening, deliberately not a separately
hand-mixed pale color -- a flat pale color only reads correctly against
one particular background, where a translucent one composites
consistently over whatever the watermark happens to cross (images,
table fills, other text). Gradients (spec §7.4) are real, usable as `design.slide
.background_gradient` (the slide's own native background fill,
`design.slide.background` remains its unused-once-set fallback) or as a
`shape_styles` entry's `fill` (`deckifyr.schema.design.Gradient`/
`GradientStop`, alongside the existing plain-color `fill: str`) --
`deckifyr.plan.resolve_gradient` resolves each stop's `color` through
`design.colors` the same "token or bare literal" way every other color
field already does. `python-pptx`'s own `FillFormat.gradient()`
installs a fixed two default stops and its `gradient_stops` collection
(`_GradientStops`) is a read/write-in-place `Sequence` with no public
way to add or remove a stop -- confirmed directly against its source,
not assumed from docs -- so `deckifyr.pptx.compose._apply_gradient`
rebuilds the `<a:gsLst>` element's children via lxml for an arbitrary
stop count, the same confined-OOXML-workaround pattern
`_set_cell_borders` already uses for a different `python-pptx` gap
(both now share the `_DRAWINGML_NS` constant), verified against a real
`.pptx` reopened with `python-pptx` for both a 2-stop and a 3-stop
gradient (exact stop colors/positions and gradient angle all
round-tripped). It still calls the public `fill.gradient()` first (that
installs the `<a:lin>` element `gradient_angle`'s own public setter
requires) and sets the angle via that public setter -- only the stop
list itself is hand-built. `Gradient.angle` follows `python-pptx`'s own
convention (0 = left-to-right, increasing = clockwise, so 90 =
top-to-bottom), not CSS's `linear-gradient()` convention. Color-token
derivation (spec §7.4, issue #11) is real: a `colors:` entry may be a
`deckifyr.schema.colors.ColorDerivation` (`base` plus exactly one of
`lighten`/`darken`/`saturate`/`desaturate`/`mix`+`weight`) instead of a
literal hex string, computed via stdlib `colorsys` (RGB<->HLS
conversion) rather than a new third-party dependency -- `colorsys`
already supplies the one genuinely non-trivial part, and
lighten/darken/saturate/desaturate/mix are each a few lines on top of
it, which doesn't clear the bar this repo otherwise holds new
dependencies to (Pillow/pyarrow/pymupdf are each pulled in for real
domain-specific parsing/rendering work, not a handful of HLS
arithmetic). `deckifyr.schema.colors.resolve_color_tokens` is the one
place derivations get expanded to literal hex strings, following
`base`/`mix` chains to arbitrary depth and raising `ColorResolutionError`
on a circular chain (its only failure mode -- a `base`/`mix` name that
isn't itself a `colors:` key is treated as a literal, the same
"token or bare literal" fallback `design.colors.get(token, token)`
already uses everywhere). It's called exactly once, from
`deckifyr.cli._load_project` right after `design.yaml` is parsed --
deliberately not from `deckifyr.plan` (where `resolve_gradient` and
friends live), because `deckifyr.plan.expand_presentation` and
`deckifyr.pptx.compose` both read `design.colors` directly off the
same `DesignDocument` instance `cli.py` hands each of them
independently (`plan.py` has 5 `design.colors.get(...)` call sites,
`compose.py` has 5 more); resolving anywhere other than that one
shared choke point would leave one side still seeing unresolved
derivations. Resolving in `_load_project` also means `deckifyr
validate` catches a circular derivation for free, with no extra
plumbing. No `deckifyr:` schema version bump was needed -- confirmed
via git history that `SUPPORTED_SCHEMA_VERSIONS` has never been
bumped for any prior purely-additive optional field (Gradients,
`StatusFurniture`, `TextStyle.opacity`, ...), and this follows the
same shape. Speaker notes
(spec §7.1/§18 Phase 1,
`Slide.notes` in `presentation.yaml`) are real: a plain string, not a
slide element -- no box/style/z_index, no design-token resolution --
that `deckifyr.plan.expand_slide` carries straight through onto
`ResolvedSlide.notes` and `deckifyr.pptx.compose` writes to the native
PowerPoint notes page (`slide.notes_slide.notes_text_frame`) via
`python-pptx`, not through the ordinary element pipeline. The
reportifyr magic-string resolver (spec §9.1, Phase 2's first slice) is
real: a `type: reportifyr` element's `value` (or a `table` element's
`source`) may be a `{rpfy}:name.ext` reference, resolved by
`deckifyr.resolvers.ReportifyrResolver` against
`build.reportifyr.outputs_dir` (default `OUTPUTS`, searched recursively)
and that artifact's `<name>_<ext>_metadata.json` sidecar --
`{rpfy}:[a, b, ...]` multi-figure references use only the first entry
and record a build warning for the rest (basic multi-figure tiling is
still an open design question, spec §21), and a resolved artifact with
no metadata sidecar fails the build unless
`build.reportifyr.fail_on_missing_metadata: false`. The sidecar's
`meta_type`/`abbreviations` are looked up in
`build.reportifyr.standard_footnotes` (a project-relative
`standard_footnotes.yaml`, required only once some element actually
needs it) to build a plain `Source`/`Notes`/`Abbreviations` footer --
this is deckifyr's own PPTX-native footer format, not a port of
reportifyr's private, config-driven Word-footnote formatting (see
`deckifyr.resolvers.reportifyr`'s module docstring for what was checked
before deciding that). `footer_placement` (`below`, the default;
`notes`; or `none`) controls whether that footer becomes a text shape
beneath the element's box (`design.yaml`'s `defaults.footer_height` for
geometry) or gets appended to the slide's speaker notes instead --
valid only on a `reportifyr` element or an `{rpfy}:`-sourced `table`,
rejected elsewhere. Footer typography (`defaults.footer_style`) reuses
`deckifyr.plan.resolve_text_style` -- the same function
`text`/`markdown`/`table` styling already goes through -- rather than a
footer-specific subset of fields, so every field a `text_styles` entry
carries (font, size, color, bold, italic, and anything added later)
is inherited by a footer automatically; `deckifyr.pptx.compose`'s
`_resolve_footer_style` only supplies the built-in fallback
(`Arial Narrow`/10pt/`colors.muted`) when `footer_style` is unset, as a
complete `ResolvedTextStyle` of its own so both branches are the same
shape. Don't reintroduce a hand-picked tuple of footer font fields here
-- that was tried once and quietly dropped `bold`/`italic`. Don't assume
any command beyond `init`/`validate`/`build`/`schema` does real work
without checking
`inst/python/deckifyr/cli.py` first.

## Components

| Path | What it is | Language |
| --- | --- | --- |
| `R/` | Thin facade (`deck_validate()`, `deck_build()`, `initialize_deck_project()`, ...) delegating to the bundled Python CLI via pyro. `R/run-python.R` is the single bridge point every other `R/*.R` file calls through. | R |
| `inst/python/deckifyr/` | The canonical engine. Bundled unmodified into the R package (`inst/python`) and also the source directory for the standalone Python wheel (spec §5.3) -- never fork this tree for one facade or the other. | Python |
| `inst/examples/minimal-deck/` | A minimal valid `design.yaml`/`layouts.yaml`/`presentation.yaml` trio. Used by `deckifyr init` as its template, and as the shared test fixture for both `tests/python/` and `tests/testthat/` -- don't duplicate its content elsewhere. Ships inside the R package/Python wheel (it's under `inst/`). | YAML |
| `examples/demo-deck/` | A richer, repo-only demo (in the spirit of quartifyr's `examples/demo-report`) -- a four-slide deck resolving a real `reportifyr`-produced figure via a real `{rpfy}:conc-time.png` reference (with a footer built from its metadata sidecar + this directory's own `standard_footnotes.yaml`), a `table` element, a multi-zone layout, rotation, and `z_index`. Not bundled into the package (outside `inst/`); see its own README.md for what it demonstrates. | YAML |
| `tests/python/` | pytest, unit-level: units, merge, schema loading, CLI exit codes, plan expansion, PPTX composition -- plus `test_demo_deck.py`, an end-to-end build of `examples/demo-deck/`. | Python |
| `tests/testthat/` | R tests, including `test-wiring.R`, the only test that exercises the real R -> pyro -> Python round trip end-to-end (not just function signatures). Skips cleanly without `uv`/`pyro`. | R |
| `.github/workflows/ci.yml` | `python-tests` (pytest matrix) + `full-pipeline` (the real R -> pyro -> Python integration proof, `tests/testthat/` run directly against the checkout). | YAML |
| `.github/workflows/R-CMD-check.yaml`, `test-coverage.yaml` | Standard, largely unmodified r-lib templates (`check-r-package`, `test-coverage`), modeled on quartifyr's own versions of the same two files -- package structure/docs/coverage only; `tests/testthat/`'s pyro-dependent tests skip cleanly under both by design (see CLAUDE.md's architecture notes). | YAML |

## Commands

### Python

```bash
uv run --extra dev pytest tests/python -v      # full suite
uv run deckifyr validate inst/examples/minimal-deck/presentation.yaml
uv run deckifyr --json validate ...             # structured output
uv run deckifyr schema presentation             # dump a document type's JSON Schema
uv run deckifyr init some-dir                   # scaffold from the bundled example
```

### R

```r
devtools::load_all(".")
testthat::test_dir("tests/testthat")
deck_validate("inst/examples/minimal-deck/presentation.yaml")
```

`NAMESPACE` and `man/*.Rd` are roxygen2-generated (`Rscript -e
'roxygen2::roxygenise()'`) -- see `CONTRIBUTING.md`. CI's
`R-CMD-check.yaml` workflow runs a real `R CMD check`
(`r-lib/actions/check-r-package`), which fails if either is stale
relative to `R/*.R`'s `#'` doc comments.

## Architecture notes that span files

**"One engine, two facades" is a hard invariant, not a starting
preference.** Schema validation, merging, geometry, and (eventually)
PPTX composition live only in `inst/python/deckifyr/`. `R/run-python.R`
is the *only* place R talks to Python; every other `R/*.R` file calls
`.run_deckifyr_cli()` rather than reimplementing any part of the
contract. If you're tempted to validate a YAML field in R "just to give
a faster error," don't -- that's exactly the drift spec §20's warning 1
calls out ("Do not maintain independent R and Python presentation
engines. They will diverge.").

**`pyro::run_python_script()` discards stdout/stderr on any non-zero
exit -- confirmed against a real pyro install, not just inferred from
docs.** It wraps `processx::run(..., error_on_status = TRUE)` in a
`tryCatch` that, on failure, throws a bare `"<script_name> failed."`
with no access to what the subprocess actually printed. Since
`deckifyr`'s CLI legitimately exits non-zero for ordinary validation/
not-implemented errors (spec §11.1 requires this), that would silently
swallow every real diagnostic the Python side produces. The fix, live in
`R/run-python.R` and `inst/python/deckifyr/cli.py`'s `main()`, is a
two-sided handshake:
  1. `cli.py` writes its structured JSON error payload to **stderr**
     (not stdout) whenever it's about to exit non-zero; stdout is
     reserved for the success path.
  2. `run-python.R` passes its own `stderr_callback` to
     `run_python_script()`. processx invokes that callback per output
     chunk *while the process is still running*, before the exit-status
     check fires -- so the callback has already captured the JSON error
     by the time pyro's wrapper throws its generic message. The R side
     catches that generic error, re-parses its own captured stderr as
     JSON, and raises the real `code`/`message` instead.

  Don't change one side of this without the other -- e.g. moving the
  error JSON back to stdout in `cli.py` silently breaks R's error
  reporting again (the CLI itself would look fine; only
  `deck_validate()`/`deck_build()`'s error messages would go back to a
  useless generic string).

**A bare `{ ... }` block passed as `tryCatch()`'s `expr` does not get
its own environment -- a real bug this repo hit, not a hypothetical.**
An earlier version of `.run_deckifyr_cli()` declared
`raw_stdout <- NULL` in the function's own frame, then tried to set it
from inside the `tryCatch(expr = { ... }, ...)` block with
`raw_stdout <<- result$stdout`. Because the block shares the calling
frame (braces aren't a scope boundary the way a `function()` body is),
`<<-` skipped right past that local binding and wrote to a *further*
enclosing environment instead, leaving the local `raw_stdout` `NULL`
forever -- every successful call silently reported "did not return
valid JSON" with empty stdout. The fix: have the `tryCatch` expression
*return* the value (or the caught `error` condition) and branch on that
returned object afterward, rather than mutating an outer variable from
inside the expression. `capture_stderr()`'s own `stderr_lines <<- ...`
a few lines away is fine by contrast -- it's inside an actual
`function(chunk, proc) { ... }`, which is a real closure, so `<<-`
there correctly reaches the enclosing frame where `stderr_lines` lives.
If you're about to write `<<-` inside a `tryCatch`/`withCallingHandlers`
block, ask whether that block is a real function or just braces.

**Unit model: YAML always spells units out; EMU only internally (spec
§7.3).** `deckifyr.schema.units.parse_length()` is the only place that
conversion happens, and only there does "unitless" get a strict/
permissive distinction -- pydantic models in `schema/design.py`/
`layouts.py`/`presentation.py` keep box/length fields as raw strings on
purpose, so a validated document can still be inspected or
re-serialized as the YAML a user recognizes. Don't pre-convert to EMU
inside a pydantic model.

**Merge precedence (spec §7.2) is one pairwise operation
(`deckifyr.schema.merge.deep_merge`) folded over a precedence-ordered
layer list, not a bespoke merge per document type.** Dicts merge
recursively; scalars and lists replace outright. If a future element
type needs additive list behavior, that's a schema-level opt-in on that
field, not a change to `deep_merge` itself.

**Shell/fill two-pass model (spec §6) mirrors quartifyr's conceptual
split but is not shared code with it.** quartifyr's pass 1 (shell) /
pass 2 (fill via `reportifyr`) is for `.docx`; deckifyr's own pass 1
(plan/shell) / pass 2 (resolve/compose) is for `.pptx` and does not call
`reportifyr`'s DOCX fill pipeline at all (spec §9.1) -- only its
documented `{rpfy}:` magic-string contract and metadata sidecars, via
`deckifyr.resolvers.ReportifyrResolver` (real, spec §9.1/9.2).

**Reportifyr integration reads its data contract, not its internals --
checked, not assumed.** Before building `ReportifyrResolver`, I checked
whether reportifyr exposes a real, exported API deckifyr could depend on
instead of reimplementing anything (the same way quartifyr's own
`render_report()` calls `reportifyr::build_report()` directly, R to R --
`Imports: reportifyr` in quartifyr's `DESCRIPTION`). It doesn't, for
what deckifyr needs: `reportipyr` (reportifyr's bundled Python engine)
declares `__all__ = []` -- no exported Python API, only a docx-mutating
CLI -- and reportifyr's real R `NAMESPACE` exports `get_meta_type()`/
`get_meta_abbrevs()` (list the *keys* in `standard_footnotes.yaml`, not
resolvers) and `add_footnotes()` (a whole-`.docx`-in/`.docx`-out
mutator), none of which return one artifact's footer text as data with
no docx side effect -- and this repo's pyro wiring only goes R to
Python, so even those R exports aren't reachable from
`deckifyr.pptx.compose` without new infrastructure. So
`ReportifyrResolver`/`build_footer_lines` in
`deckifyr/resolvers/reportifyr.py` read reportifyr's real, documented
*data* contract instead -- the `{rpfy}:` magic-string grammar and the
metadata JSON sidecar schema (produced by reportifyr's exported
`write_object_metadata()`) -- and build deckifyr's own plain
`Source`/`Notes`/`Abbreviations` footer format from those fields, not a
port of `reportipyr`'s private, config-driven Word-footnote formatting
(`footnote_order`, `wrap_path_in_[]`, etc. -- Word-specific rendering
choices, not part of the contract). If reportifyr ever exports a
docx-free "resolve this artifact's footer text" function, that's the
real fix to revisit this against -- not a reason to guess at its
internals in the meantime.

**Quarto integration (spec §8/§8.1, issue #3) is real, built against a
live `quarto`/Typst/PyMuPDF toolchain, not just designed against the
spec.** `deckifyr.renderers.quarto` executes a `type: quarto` element's
`.qmd` fragment and turns it into either normalized text (`render_mode:
native`, reusing `deckifyr.pptx.compose._add_text_shape`'s existing
Markdown parsing for Quarto's own `--to gfm` output -- no second
Markdown renderer) or a rasterized `png` (`render_mode: png`, via
`--to typst` -- chosen over `--to pdf` specifically because Typst is
bundled with Quarto and needs no separately-installed LaTeX engine,
confirmed against a real `quarto check` with no TinyTeX present).
`deckifyr.resolvers.quarto.QuartoResolver` wraps it as an ordinary
`ContentResolver` (spec §9.2); `deckifyr.pptx.compose._add_quarto_shape`
places the result exactly like a `markdown`/`image` element, never
Quarto's own PPTX writer (spec §20 warning 2).

**`render_mode: svg` cannot actually reach the compositor -- confirmed
against a real render, not assumed from docs.** `python-pptx` has no
SVG embedding support at all (`pptx/package.py` explicitly skips SVG as
an "unknown/unsupported image type" on insertion), and separately
`_place_picture`'s own Pillow-based sizing can't open an SVG either --
first discovered as a real `PIL.UnidentifiedImageError` crash while
writing `tests/python/test_pptx_quarto.py`'s end-to-end math test, not
reasoned out in advance. `deckifyr.renderers.quarto.render_image` still
supports `image_format="svg"` (it's a real, independently useful
capability, and a future non-PPTX consumer of a resolved plan might
want it), but `select_auto_render_mode` never picks it, and
`_add_quarto_shape` raises a clear `ContentValidationError` if an
element explicitly sets `render_mode: svg` -- pointing at `png` instead
-- rather than letting the Pillow crash surface. Don't reintroduce `svg`
as an `auto`-selectable or silently-accepted compositor render mode;
the spec's own render-mode table already flags this under svg's
"limited editability and support variability" tradeoff.

**A Typst page defaults to a fixed size (e.g. US Letter) with a page
number footer on; getting a clean, fragment-sized crop instead needed
two empirical fixes, not just reading Quarto's docs.** The
natural-looking approach for the sizing half -- passing a `#set
page(width: auto, height: auto)` rule via Pandoc's own
`--include-in-header` -- was tried first and verifiably does not take
effect (confirmed with a real render: the PDF still comes back at
612x792pt); Quarto's own Typst template evidently re-establishes page
defaults after that injection point. What actually works, confirmed
against a real render producing a tight content-sized PDF (verified via
PyMuPDF's own `page.rect`): splicing that same `#set page(...)` rule as
a raw Typst block (`` ```{=typst} ``) directly into the fragment's own
body, after any YAML frontmatter. `render_image` does this by writing a
throwaway sibling `.qmd` file next to the original (so relative
resource references in the fragment still resolve against the real
project directory) rather than mutating the user's own file, and always
deletes it in a `finally`. The second fix was caught only by actually
looking at a real rendered PNG while building `examples/demo-deck`'s
equation slide: a literal "1" baked into the image, from Quarto's Typst
template's own default `numbering: "1"` page-number footer, which the
sizing-only `#set page(...)` override didn't touch (Typst's `set` only
overrides the fields you name). `numbering: none` was added to the same
injected `#set page(...)` call to kill it -- a good example of why this
module's tests were run against real output, not just "it built without
erroring."

**A rasterized `png`/`svg` fragment's prose now matches the deck's own
font/color by default -- also caught by looking at a real render, not
anticipated up front.** Without an explicit font, Typst renders in its
own default serif typeface, which reads as visibly inconsistent sitting
next to ordinary Arial-set native text on the same slide (first seen on
`examples/demo-deck`'s equation slide). `_inject_typst_autosize` now
also splices a `#set text(font: ..., fill: rgb(...))` rule using
`element.style`'s resolved font/color (or `design.yaml`'s own
`fonts.body`/`colors.text` when the element sets no `style:`, mirroring
`_add_text_shape`'s own fallback) -- `deckifyr.pptx.compose
._add_quarto_shape` computes and passes these into `QuartoResolver
.resolve`/`render_image` as `font`/`text_color`. Deliberately does
*not* touch `math.equation`'s own font: Typst's math mode needs a font
with a real math table (glyph variants, spacing metrics) that an
ordinary UI typeface like Arial doesn't have, and confirmed against a
real render, `#set text(font: ...)` alone already leaves equations in
Typst's own math font while only retypesetting the surrounding prose --
exactly the outcome wanted, not a gap to close.

**Rasterizing an equation to `png` instead of a native, editable
PowerPoint equation is a real, documented gap in this module's own
scope -- not a technical dead end, and not something to hand-wave
past.** `python-pptx` has no API for inserting OMML (`<m:oMath>`,
PowerPoint's native equation markup) -- confirmed, that part really is
a hard limitation of the library layer everything here is built on. But
Quarto/Pandoc's own `--to pptx` writer *does* emit real native
`<m:oMath>` equations -- confirmed by actually rendering
`$$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$$` through `quarto render x.qmd
--to pptx` and inspecting the slide XML: a genuine `<a14:m>
<m:oMathPara><m:oMath>...` element, not a picture. So a `native`
equation-render path is possible in principle -- pull the same OMML
Pandoc already generates (via a full `--to pptx`/`--to docx` render) out
of its output XML and splice that fragment into one of
`deckifyr.pptx.compose`'s own text runs, the same kind of narrow OOXML
adapter `_set_cell_borders`/`_set_alt_text` already are for other
python-pptx gaps below. It isn't built here because that splice needs
real namespace/content-type wiring (`a14:`/`m:` declarations,
`mc:AlternateContent` fallback content) verified against a real
PowerPoint install, the same correctness bar `_set_cell_borders`'s own
note above was held to -- not something to attempt without that
verification. See `deckifyr.renderers.quarto`'s own module docstring
for the fuller writeup; treat this as a well-scoped, tracked future
improvement (spec §21-style open decision), not a closed question.

**The `.qmd` "single fragment" complexity limit (spec §8.1) is a text
heuristic, not a real document-structure parse, and that's a known,
accepted gap, not an oversight.** `check_fragment_complexity` rejects a
Markdown horizontal-rule-shaped line (`---`/`***`/`___`, outside the
YAML frontmatter and fenced code) and more than one top-level `#`
heading. A setext-style heading (`Title\n-----`) can false-positive on
the first check; spec §8.1 itself frames the exact limit as still open,
so this repo's own convention is ATX (`#`) headings in a fragment, not
setext. Don't try to "fix" this into a full CommonMark parse without
revisiting whether that's still proportionate to the limit spec §8.1
actually asks for.

**Every `quarto`-related test that needs the real `quarto` binary skips
cleanly when it's absent, mirroring `tests/testthat/test-wiring.R`'s own
uv/pyro skip pattern -- confirmed against a real run with `quarto`
hidden from `PATH`, not just reasoned about.** CI's `python-tests` job
(`ci.yml`) does not install Quarto, so
`tests/python/test_renderers_quarto.py`,
`tests/python/test_resolvers_quarto.py`, and the end-to-end tests at the
bottom of `tests/python/test_pptx_quarto.py` gate on
`shutil.which("quarto")` (an R-chunk-executing test additionally gates
on `shutil.which("Rscript")`); everything else in those files -- the
complexity-limit and `render_mode: auto` heuristics, path-safety checks,
and the fast `test_pptx_quarto.py` tests that monkeypatch
`deckifyr.pptx.compose.QuartoResolver` with a canned artifact -- runs
unconditionally. This is expected, honest local/CI behavior per this
file's own testing-strategy precedent (see the R-CMD-check.yaml note
above), not a gap to paper over with mocking the real binary everywhere.

**`presentation.yaml`'s `build.quarto` block (`binary`/
`timeout_seconds`/`max_output_bytes`) mirrors `build.reportifyr`'s own
"required only lazily" shape.** `deckifyr.schema.presentation.QuartoConfig`
is `None` by default; `deckifyr.pptx.compose._build_quarto_config` reads
it only when present, falling back to `QuartoExecutionConfig`'s own
defaults otherwise -- a build with no `quarto` element never touches
this at all, same precedent `ReportifyrBuildContext`/
`_build_reportifyr_context` already set.

**Preview rendering (spec §12/§18 Phase 3, closing the CLI's `preview`
stub) shells out to LibreOffice rather than inventing a from-scratch
layout engine -- resolving spec §21's open "select the initial preview
renderer" item.** `python-pptx` has no rendering engine of its own; this
repo's own `.githooks/pre-commit`/`examples/demo-deck/README.md` already
documented `soffice --headless --convert-to pdf` + PyMuPDF rasterization
as the manual recipe for regenerating `man/figures/demo-deck-*.png`, so
`deckifyr.renderers.preview.render_slide_previews` just wires that
same, already-trusted recipe into the CLI instead of building a second
renderer -- real PowerPoint-engine fidelity (fonts, gradients, tables,
rotation all render the way LibreOffice's own layout engine actually
lays them out), at the cost of a real external-binary dependency,
mirroring the `quarto` binary's own story exactly (`_require_soffice`/
`_require_quarto`, same shape). `presentation.yaml`'s `build.previews:
true` (spec §7.6's own example -- a schema field that sat completely
unused until this) is the on/off switch for rendering previews as part
of an ordinary `deckifyr build`; the new `build.preview` block
(`binary`/`dpi`/`timeout_seconds`, `deckifyr.schema.presentation.
PreviewConfig`) mirrors `build.quarto`'s own "`None` means every
default applies" shape. `deckifyr preview`/`deck_preview()` always
render regardless of that flag (`compose_and_write`'s own
`force_previews=True`) -- the point of a standalone preview command is
not needing to permanently flip a project's config just to check one
preview. Previews land in `<build.output's parent>/previews/`, named
`<pptx stem>-<01-indexed slide number>.png`, and their paths are
recorded in both the CLI's JSON result and the manifest's own
`"previews"` key, the same additive-key pattern `"warnings"` already
established -- no existing manifest consumer asserts an exhaustive key
set, confirmed by checking every `manifest[...]` test-file reference
before adding this.

**`deckifyr inspect` (spec §11.1) detects a presentation.yaml versus a
built `.pptx` by file extension (`.yaml`/`.yml` vs `.pptx`), not by
sniffing content -- there is no third possibility spec §11.1 names.**
Given a presentation, it plans (`deckifyr.plan.expand_presentation`,
the same Pass 1 `build`/`validate` already use) and reports the
resolved slide list -- element counts/types, notes presence -- without
composing or writing anything, so `inspect` on a large project stays
cheap and side-effect-free. Given a `.pptx`, it opens the file for real
with `python-pptx` and reports what's actually inside (per spec §13's
"Output validation" bullets: slide/shape counts, shape names, rotation,
notes presence) -- not a re-derivation from YAML, since the point of
inspecting a *built* artifact is seeing what actually landed in it.
`_inspect_pptx` also opportunistically looks for a sibling `<pptx
stem>.manifest.json` (the `<stem>.pptx`/`<stem>.manifest.json` naming
convention both bundled example projects already use) and includes a
short summary of it when found -- best-effort, not required; nothing
about `inspect`'s own contract depends on a manifest existing.

**A missing external binary (LibreOffice, Quarto) now raises a
distinct, structured error -- `deckifyr.schema.errors.
MissingDependencyError` (`ContentValidationError` subclass, code
`E_MISSING_DEPENDENCY`) -- specifically so `R/run-python.R` can react to
it, not just display it.** Its `to_dict()` adds a `dependency` object
(`name`/`display_name`/`install_url`) to the CLI's JSON error payload
(the same stderr handshake this file documents elsewhere -- see the
`pyro::run_python_script()` note below) alongside the usual `code`/
`message`. `.run_deckifyr_cli()`'s `.handle_missing_dependency()` is the
one place that reads it: always prints a `cli`-formatted panel naming
the dependency and its official download page; on macOS, with Homebrew
already on `PATH`, in an interactive session, additionally offers to
run the verified-correct `brew install --cask <name>` command itself
(confirmed against Homebrew's own cask listings for both `libreoffice`
and `quarto` before writing this, not guessed) -- no `sudo` needed, so
safe to run without extra privilege escalation. Every other platform/
dependency combination just gets the printed URL: there's no single
install command deckifyr can verify in advance for apt/winget/etc, and
this deliberately never guesses one or runs anything needing `sudo`.
`interactive()` gates the install-offer branch, which also means this
never fires during automated test runs (testthat sessions are
non-interactive) -- don't remove that gate to make a test "more
realistic"; it's what keeps CI from ever actually invoking Homebrew.

**The web application (spec §12, issue #2) is real: a FastAPI backend
(`deckifyr.web.app`/`deckifyr.web.jobs`) serving a built React/
TypeScript + react-konva frontend, `deckifyr serve`/`deck_serve()` as
its entry points.** `deckifyr/projectio.py` is a new module extracted
out of `cli.py` specifically to make this possible without a second
implementation -- the same "mechanism in its own module, orchestration
in `cli.py`" split `deckifyr.plan`/`deckifyr.editor` already
established, moving `load_project`'s schema/geometry validation and the
`get`/`set`/`slide` commands' shared `read_yaml`/`write_yaml`/
`parse_json_arg`/`validate_and_write_presentation` helpers into a
module with zero argparse/JSON-envelope code of its own -- its own
docstring says so explicitly ("this module exists as its own thing
specifically so a forthcoming `deckifyr.web`... can load/validate/write
the same project files without importing `deckifyr.cli` for it"), and
`deckifyr.web.app` is exactly that forthcoming caller now realized:
`create_app`/`patch_element`/`put_config` all call straight into
`projectio`/`editor`, never re-deriving path resolution or validation.
`create_app(project_root, presentation_name)` binds to one project root
and one `presentation.yaml` for the lifetime of the process -- matching
spec §12.0's own "not a website for a general audience" framing
(`deck_serve()`'s single-project, launched-from-an-IDE-session model,
the same mental model as `shiny::runApp()`) -- and every route resolves
`design.yaml`/`layouts.yaml` off that one bound presentation via
`presentation.design.base`/`presentation.layouts`, the same resolution
`projectio.load_project` already does elsewhere. Handlers return plain
`dict[str, Any]` (`app.py`'s own docstring), not a second, parallel
pydantic response-model layer restating what `deckifyr.schema` already
defines. `POST /api/build` never composes in-process -- it hands off to
`deckifyr.web.jobs.JobManager.submit_build`, which runs a real `python
-m deckifyr --json build ...` subprocess on a background thread and
polls it, honoring spec §12.0's own warning that "FastAPI background
tasks are not a substitute for a durable or isolated rendering worker"
by never composing inside the request process at all; `JobManager
._run_build` reuses the CLI's own stdout-JSON-on-success/stderr-JSON-
on-failure handshake (the same one `R/run-python.R` relies on,
documented elsewhere in this file) rather than inventing a second error
format. The artifact-download route (`GET /api/jobs/{id}/artifacts
/{key}`) only ever looks `key` up in `Job.artifacts`, a dict
`JobManager` itself populated from that job's own build result
(`pptx`/`manifest`/`preview-N` keys) -- never a raw filesystem path
taken from the request, so a request can't reach any file outside what
that job actually produced (`jobs.py`'s own docstring is explicit about
this). `cli.py`'s `_cmd_serve` imports `uvicorn` lazily, inside a
`try`/`except ImportError` that raises a clear `DeckifyrError` pointing
at the optional `web` extra -- the same posture `deckifyr.resolvers
.table`'s lazy `import pyarrow.parquet` (Parquet table sources) and
`deckifyr.renderers.quarto`'s lazy `import pymupdf` (PNG/SVG
rasterization) already established for their own optional dependencies,
so every other subcommand keeps working without `fastapi`/`uvicorn`
installed. On the frontend, `web/src/components/SlideCanvas.tsx`'s own
`DRAGGABLE_TYPES` is `text`/`markdown`/`image` -- those three render as
real Konva `Group`s that can be dragged, resized, and rotated
(committing back through `PATCH /api/slides/{slide}/elements
/{element}`, or, on the furniture pseudo-slide, `PATCH /api/furniture
/elements/{element}` -- see this section's own furniture-pseudo-slide
paragraph below); `shape`/`group`/`table`/`reportifyr`/`quarto` elements
render as a static, labeled, dashed placeholder box, per that
component's own module comment naming this as this project's deliberate
scope. `image` is draggable/resizable/rotatable like text, but still
renders as a labeled placeholder rather than the real picture --
confirmed against both the component and the API it calls: `GET
/api/plan` (`app.py`'s `_serialize_element`) only ever returns an image
element's `source` path (`deckifyr.plan.ResolvedElement.source`), never
its pixels, and there is no route anywhere in `app.py` that serves a
project image's bytes, so the canvas has nothing to paint even though
the interaction chrome around it is real. `ConfigEditor.tsx` edits
`design`/`layouts`/`presentation` as pretty-printed JSON in a plain
`<textarea>`, not YAML and not a schema-driven form -- its own module
comment gives the reasoning: `GET`/`PUT /api/config/{doc}` (`app.py`'s
`get_config`/`put_config`) are already JSON-native end to end, so a
YAML stringify/parse dependency would only buy cosmetic parity with the
on-disk file's own syntax, not a functional need this editor has, and a
real YAML round trip (comments, anchors, block scalars) is a much
bigger dependency surface than this repo's own low-dependency precedent
(`colorsys` over a color-math library) was willing to clear for a much
smaller win -- server-side validation (`PUT`'s `model_validate`/
`validate_and_write_presentation`) still rejects a bad edit before it's
written, same as `deckifyr set`. (A schema-driven form generated from
`GET /api/schemas/{doc}` was this paragraph's own documented future
scope at the time it was written -- now built, see this section's own
config-editor paragraph below; `ConfigEditor.tsx` no longer stays JSON-
textarea-only, though the JSON-not-YAML reasoning above is unchanged.)
The built frontend under `inst/python
/deckifyr/web/static/` (`index.html` + hashed `assets/*.js`/`*.css`) is
committed generated output, the same posture `man/figures/*.png`
already has -- neither `pip install` nor `R CMD build`/`R CMD INSTALL`
can run an `npm run build` at install time, so the built artifacts have
to already be on disk for `deckifyr.web.app.create_app`'s
`StaticFiles` mount to find; `pyproject.toml`'s `[tool.setuptools
.package-data]` (`"deckifyr.web" = ["static/**/*"]`) is what actually
ships them inside the wheel. On the R side, `deck_serve()` cannot reuse
`.run_deckifyr_cli()` -- that helper is fully synchronous
(`pyro::run_python_script()` blocks until the subprocess exits) and
would hang forever against a long-running server, so `R/serve.R`
launches Python in the background via `processx::process$new()`
instead, wrapped in its own one-line `.launch_server_process()`
function rather than called directly -- confirmed the reason in that
function's own doc comment: `testthat::local_mocked_bindings()` can
only replace a binding that already exists as a named object, and
`process$new` is an R6 generator method rather than a plain function
binding, so it can't be mocked directly (mocking `new` via `.package =
"processx"` was tried and errors with "Can't find binding for `new`").
Readiness is polled via `.wait_for_server()`'s plain TCP connect
against `host`/`port`, itself built on a new `socketConnection <- NULL`
seam appended to `R/run-python.R`'s existing NULL-seam block (the same
`testthat`-mockability trick that block's own comment already documents
for `system.file`/`interactive`/`system`/`Sys.info`/`Sys.which`) -- and
once reachable, `deck_serve()` opens the server's URL via
`rstudioapi::viewer()` when running inside RStudio (a new
`Suggests`-only soft dependency, `DESCRIPTION`) or `utils::browseURL()`
otherwise.

**The furniture pseudo-slide (issue #21) is real: a synthetic
"⚙ Furniture" entry in the slide list shows design.yaml's `furniture`
block on its own canvas, editable with the same drag/resize/rotate
machinery real slide elements use, backed by `GET`/`PATCH`/`POST`/
`DELETE /api/furniture[/elements/{id}]`.** `GET /api/furniture` builds
a synthetic `Slide(id="__furniture__", layout=None)` and calls
`deckifyr.plan.expand_slide` on it directly -- `expand_slide` already
computes furniture elements internally and merges them with whatever
`layout` is passed, so `layout=None` makes it return exactly the
furniture elements with zero new plan.py resolution logic. `plan.py`'s
`FURNITURE_*_ID`/`STATUS_INDICATOR_FIELDS` (previously `_`-prefixed
module-private) are now public for this reason. PATCH/POST/DELETE
resolve a furniture element id to a dotted path into `design.yaml`'s
raw dict (`furniture.status.<field>`/`furniture.branding`/
`furniture.page_number`) and reuse the same validate-then-write shape
`put_config`/`patch_element` already use; a field a kind's schema
doesn't have (rotation/z_index on branding/page-number, `value` on
anything but branding's own `text`) is a hard 422, never a silent
no-op, matching spec §20 warning 7.

Two real bugs surfaced only by actually using this against
`examples/demo-deck`, not by reasoning about the code:

- **Konva's default rotation pivot is a node's own `(x,y)` (top-left);
  `python-pptx`/OOXML's `<a:xfrm rot="...">` rotates a shape around its
  own *center*.** Every rotated furniture placement (the watermark at
  -30°, every corner at ±90°) was previewing at the wrong position --
  a configured `corner_tr` placement's text swung up past the slide
  entirely and was, in practice, unfindable. Fixed in
  `SlideCanvas.tsx` by positioning every draggable/placeholder `Group`
  at its box's *center* (`x + width/2, y + height/2`) with a matching
  `offsetX`/`offsetY` (children still drawn at local `(0,0)`, unchanged
  visually at `rotation: 0`) -- `handleDragEnd`/`handleTransformEnd`
  convert Konva's now-center-based `node.x()`/`node.y()` back to the
  box's top-left (`centerToTopLeftPx`, exported for unit testing) before
  building a `PATCH` body, since the schema still stores top-left `x`/
  `y`. Verified against a real demo-deck corner box, not just asserted:
  the before/after `man/figures/web-app-furniture.png` diff is a good
  visual proof (the diagonal watermark placeholder used to swing up and
  overlap the title; it now stays centered on the slide).
- **`status_indicator` pointing at a placement `design.yaml` hasn't
  configured yet used to 500 the *one* screen that could fix it.**
  `_furniture_layout` (the real build/`GET /api/plan` path) correctly
  raises `ContentValidationError` there on purpose (spec §20 warning
  7) -- but `GET /api/furniture` was going through the exact same
  strict path, so picking a new placement in "Deck Options" before
  giving it a style broke the furniture editor too, with no way back
  in short of hand-editing YAML. Fixed with a new `lenient: bool`
  parameter on `_furniture_layout`/`expand_slide` (default `False`,
  every existing caller unchanged): `GET /api/furniture` passes
  `furniture_lenient=True` and gets that one element omitted instead of
  an exception, so `FurnitureControls`' own "Add" stays reachable.
  `usePlan.ts`'s `refetch` also switched from `Promise.all` to
  `Promise.allSettled` for the same reason -- a `GET /api/plan` failure
  must not also blank out `furnitureSlide`, which may have succeeded.
  Along the way, `getattr(design.furniture.status, field_name)`
  (`design.furniture.status` itself is optional, not just each of its
  fields) turned out to raise a raw `AttributeError` instead of the
  intended `ContentValidationError` whenever a project had no
  `furniture.status` block configured at all, in strict mode too -- a
  second real, previously-latent bug the same lenient-mode regression
  test caught.

Two UX corrections from the same dogfeeding session, both in
`FurnitureControls.tsx`: `PATCH /api/furniture/elements/__furniture_status`
always resolves to whichever placement `status_indicator` currently
selects, so a "Remove" button there would delete the *active*
placement's style while `presentation.yaml` still points at it,
breaking the plan for every slide -- there is no Remove for status, only
a hint pointing at the "Deck-wide" bar's own dropdown (`None`), which is
the actual safe off-switch and never touches `design.yaml`. And the
client-only "Hide" toggle (`state.hiddenFurnitureIds`, `reducer.ts` --
never sent to the server) is offered only for the full-page `watermark`
placement, not corners/background/branding: watermark is the one kind
large enough to bury everything else while positioning it (`z_index:
9999`, on top of ordinary content by design), the others are small or
sit behind content already. `DeckOptions.tsx` also gained a "Deck
status" field bound to `metadata.status` -- the actual primary input
`deckifyr.plan.resolve_watermark_text`'s own `watermark ?? metadata
.status` fallback is built around -- after a real user typed text into
what was then the only field (labeled generically "Text", writing
`presentation.watermark`) and had no way to tell what it would produce
on a *corner* placement, where nothing is a "watermark." That original
field is relabeled "Watermark override" and stays -- it's still the
right field for the rarer case where the mark itself should say
something different from the deck's own status.

**The config editor's Form/Raw toggle (issue #22) is real:
`ConfigEditor.tsx` now defaults to a schema-driven form
(`SchemaForm.tsx`) instead of a JSON textarea, with a syntax-
highlighted, live-validated raw view (`jsonHighlight.ts`) a toggle
away.** Both are dependency-free, matching this repo's existing low-
dependency precedent (`colorsys` over a color-math library) -- no
CodeMirror/Monaco/ajv. `SchemaForm.tsx` is a recursive renderer driven
by `GET /api/schemas/{doc}`'s real pydantic JSON Schema output
(`$defs`/`$ref`, `X | None` as `anyOf` with a `"null"` branch): object/
array/enum/scalar fields each get a typed input, and an open dict with
no fixed `properties` (`colors`/`text_styles`/`shape_styles`/
`table_styles`) gets an add/remove named-entry list. An `anyOf`/`oneOf`
with more than one *non-null* branch -- `colors`' own `str |
ColorDerivation` entry values are the real example -- can't be
disambiguated generically, so that one leaf falls back to a small
inline raw-JSON field instead of guessing wrong; this is a documented,
intentional scope boundary (see `SchemaForm.tsx`'s own module
docstring), the same kind this repo already keeps elsewhere (`render_mode:
svg`, unset `table_style`). `jsonHighlight.ts` is a small regex
tokenizer, not a real parser -- `JSON.parse` (now run live, on every
keystroke, not only at Save) remains the actual validation authority;
the highlighted view is the standard dependency-free trick, a
`<pre>`-with-colored-spans behind a transparent-text `<textarea>`, kept
scrolled together via `onScroll`. Switching Raw -> Form is blocked
(with an inline error) while the current raw text doesn't parse, so the
form is never handed a value that doesn't match what's on screen.

**The Layouts editor mode (issue #30) replaces issue #23's per-slide
Content/Layout tab with a persistent, app-wide toggle: `SlideList.tsx`'s
own "Slides / Layouts" buttons (`state.editorMode`, `reducer.ts`) swap
the *entire* numbered list between `presentation.yaml`'s slides and
`layouts.yaml`'s layouts, rather than re-targeting whichever slide
happened to be selected.** Every `layouts.yaml` is now required to
define a `blank` layout (`deckifyr.schema.layouts.BLANK_LAYOUT_ID`,
`LayoutsDocument`'s new `_check_has_blank_layout` validator) -- it's the
fallback `DELETE /api/layouts/{name}` reassigns affected slides to when
their own layout is removed, and it can never itself be removed
(`editor.remove_layout` raises `UnremovableLayoutError`). Backend layout
CRUD (`editor.add_layout`/`remove_layout`/`layouts_using`/
`reassign_layout`) and the `GET`/`POST`/`DELETE /api/layouts` routes
follow the exact precedent furniture CRUD (issue #21) and slide CRUD
(issue #23) already set: web-editor-only, no CLI subcommand or R
wrapper. `GET /api/layouts` resolves every layout eagerly (the same
`_resolve_layout_zone` `GET /api/layouts/{name}` already used), replacing
issue #23's on-demand single-layout fetch and the staleness-guard
complexity that came with it (`layoutSlideReady` in `SlideCanvas.tsx`/
`ElementInspector.tsx` is gone -- `usePlan.ts`'s `layouts` is just
another eagerly-fetched array, the same shape `furnitureSlide` already
is). Removing an in-use layout previews which slides would be
reassigned *before* the confirm even fires -- computed client-side from
`plan.slideLayouts`, no extra request needed -- but the server still
rejects the removal outright (422, nothing committed on either document)
if that reassignment would actually leave a slide unbuildable. This
was a real discovery, not a designed-in feature: a naive
"reassign to blank" against the demo-deck fixture immediately broke
`content-slide`, because its own `title` override only sets `value` and
relies entirely on its old layout's zone for `type`/`box` -- `blank` has
no zones, so the override resolved to "no element type" at
`expand_presentation` time. `remove_layout`'s route now runs that same
`expand_presentation` as a dry run (against the edited-but-not-yet-
committed `layouts`/`presentation` data) before committing either
document, surfacing the specific slide/element/reason in the 422 rather
than silently leaving the working copy in a state where an unrelated
later `GET /api/plan` call starts failing. Building this also surfaced a
real, previously-latent bug in `projectio.validate_presentation_data`:
its `slide.layout` cross-check read `layouts.yaml` from disk, which was
harmless before this feature (nothing ever edited `layouts.yaml`
in-memory-only) but silently rejected a brand-new, unsaved layout as
"unknown" the moment #30 made that possible. Fixed with a new
`layouts_data` parameter (`None` -- every pre-existing caller -- keeps
the old disk-read behavior exactly); every mutating route in `app.py`
that calls it now passes `layouts_data=working_copy.get("layouts")`.

**Element add/remove (issue #31) is real:
`deckifyr.editor.add_element`/`remove_element` work against either
document's `elements` block (a slide's own, or a layout's own zones --
both the same dict-or-list shape, spec section 7.6), backing new
`POST`/`DELETE /api/slides/{id}/elements[/{element_id}]` and
`/api/layouts/{name}/elements[/{element_id}]` routes.** A new element's
geometry is always a server-computed default box (`app.py`'s
`_new_element_fields`, reusing `_default_box`/`_slide_size_in` the same
way `_default_furniture_value` already does) -- centered, sized relative
to the project's own slide dimensions, refined afterward by the same
drag/resize the canvas already supports. `reportifyr`/`quarto` element
types get a real file picker instead of a hand-typed path: new
`deckifyr.resolvers.discovery.list_reportifyr_artifacts`/
`list_quarto_fragments`, backing `GET /api/project/files?type=...`.
`list_reportifyr_artifacts` inverts `reportifyr.metadata_sidecar_path`'s
own `<stem>_<ext>_metadata.json` naming convention (now public,
following the same "public for one specific cross-module caller"
precedent `deckifyr.plan`'s `FURNITURE_*_ID` constants set) to find
candidate artifacts, deliberately only surfacing ones that would
actually resolve (a real artifact file *and* a matching sidecar both
present) -- not every file under `outputs_dir`. On the frontend, a new
`web/src/components/ElementList.tsx` sidebar replaces both
`ElementInspector`'s old always-visible fixed slot and the standalone
`FurnitureControls` bar (deleted) that used to sit above the canvas:
one collapsed row per element, selecting a row (or the same element on
`SlideCanvas`) expands it via the one shared `state.selectedElementId`
-- the expanded content is `ElementInspector`'s existing box/rotation/
z-index form, rendered inline for whichever row is selected rather than
in its own separate sidebar slot; `App.tsx` no longer renders
`ElementInspector` directly. On the furniture pseudo-slide, the same
four fixed-cardinality Add/Remove/Hide controls `FurnitureControls` had
are now list rows instead of a horizontal strip -- still going through
`addFurnitureElement`/`removeFurnitureElement`, not the new generic
element-CRUD routes, since furniture is deliberately not generic element
CRUD (`app.py`'s own routing comment). Per-slide element counts
(`SlideList.tsx`) now exclude synthesized `__furniture_*` entries --
`slide.elements` from `GET /api/plan` includes them (furniture merges in
at plan time, spec section 7.8), so the raw `.length` `SlideList` used
to show was counting furniture as the slide's own content; shown as
`(N)*`, a `title` tooltip explaining the `*`. `SlideList.tsx` also picked
up two small polish items from the same issue's follow-up comments: a
subtle `×`/`⧉` icon pair in each row's own corner (replacing a full-width
"Remove" text button) for remove/duplicate, and duplicate
(`POST /api/slides/{id}/duplicate`, a thin wrapper over the existing
`editor.add_slide`'s own `elements`/`notes` passthrough -- no new
`editor.py` function needed) auto-names the copy `<id>-copy` (`-copy-2`,
...) with no naming prompt, since it's non-destructive and needs no
confirm step the way Remove still does.

**Build-tab improvements (issue #32) -- a real output-path directory
browser, a build-time PDF-keeping change, and a shared preview-gallery
component -- landed together as one issue but are three independent
pieces.** `deckifyr.resolvers.discovery.list_project_directory` backs a
new `GET /api/project/browse?dir=...` route: **one single level**
(`Path.iterdir()`, never `rglob`) of one project-relative directory,
capped at 500 combined entries (`truncated: true` past that). This is
deliberately not the same shape as that module's own
`list_reportifyr_artifacts`/`list_quarto_fragments`, which eagerly walk
the whole project tree -- a directory picker has to stay usable against
a project with a deep, unrelated tree it has no business walking (a
populated `renv/library`, `node_modules`, ...), so `web/src/components
/OutputPathBrowser.tsx` calls this once per directory an author actually
clicks into, never up front. Second, independent piece: `_cmd_build`
now passes `keep_preview_pdf=True` to `compose_and_write` unconditionally
(a no-op when `build.previews` is off, since no preview render happens
at all) and surfaces `preview_pdf` in its own result dict the same shape
`_cmd_preview` already had -- an ordinary `deckifyr build` with
`build.previews: true` now keeps the intermediate PDF LibreOffice
produces alongside the PNGs, not just `deckifyr preview`, mirroring that
command's own "already paying the conversion cost" reasoning. The Build
tab's new checkbox ("Render slide previews (PNG + PDF) with this
build") is bound straight to that same existing `build.previews` field --
no new schema field, since one flag now controls both outputs. Third
piece: `web/src/components/PreviewGallery.tsx` is the shared
presentation for a job's `preview-N`/`pdf` artifacts, used by both the
Build section's own results and the pre-existing standalone Preview
section (previously the latter's only consumer) -- PNG thumbnails are
small by default, a click toggles a single `expandedKey` so at most one
is ever enlarged at a time; the PDF sits behind a `<summary>Show PDF
preview</summary>` disclosure whose `<iframe>` is only actually rendered
(not just visually hidden) once opened, confirmed the hard way while
writing this: a closed native `<details>`'s children stay attached to
the DOM, so an `<iframe src=...>` inside one still loads its `src`
regardless of the `display: none` a closed `<details>` gives it --
"never fetched unless requested" needed a real React-state-gated
conditional render, not just relying on the native collapsed state.
Toggling that disclosure is handled by the `<summary>`'s own `onClick`
(`preventDefault` + flip state), not the native `"toggle"` DOM event --
confirmed against a real test failure that the HTML spec fires
`"toggle"` from a queued task, not synchronously with the click, which
would make the very next render (in real usage, not just tests) lag one
tick behind the visible native open/close for no benefit here.

**`processx::process$kill()` only kills the top-level tracked PID, not
its children -- a real bug this caused in `deck_stop_server()`, found
via a live user report, not caught by this repo's own mocked test
suite.** `deck_serve()` launches `uv run -m deckifyr serve ...`, and
`uv run` is a genuine parent/child pair, not one process exec-replacing
itself into the other -- confirmed directly (spawned `uv run python -c
'time.sleep(30)'`, then `pgrep -P` on the `uv` PID listed a separate,
live `python3` PID underneath it). `deck_stop_server()` originally
called `server$process$kill()`, which only ever reached that top-level
`uv` PID; the actual `python -m deckifyr`/uvicorn process survived as
an orphan, still bound to the port. The next `deck_serve()` call at the
same (default) port then had its own *new* process fail to bind
("address already in use") while `.wait_for_server()`'s plain
TCP-connect readiness check still reported success -- because it was
reconnecting to the *old*, stale, orphaned server the whole time, not
the new one. Net effect, exactly as reported: the R console printed a
correct-looking `deckifyr_server` object naming the newly-requested
project, while the browser/Viewer pane kept showing whatever project
the leftover orphan actually served. Fixed two ways, both needed:
`processx::process` exposes a distinct `kill_tree()` method (confirmed
via `formals()`/method listing, not assumed) that `deck_stop_server()`
now calls instead of `kill()`, and `.launch_server_process()`'s
`processx::process$new()` call now also sets `cleanup_tree = TRUE`
(mirroring `cleanup = TRUE`'s own GC-triggered safety net, but for the
whole tree) so an abandoned handle doesn't leak the child either.
*Second*, independent guard: `deck_serve()` now refuses to launch at
all when `.port_is_open(host, port)` (a small helper factored out of
`.wait_for_server()`'s own TCP-connect check) is already `TRUE` --
raising a clear "port already in use" error before ever spawning a
doomed process, so *any* leftover occupant of that port (a process this
fix didn't clean up, e.g. from an R session that crashed before this
fix existed, or genuinely something unrelated) fails loudly instead of
silently misdirecting the caller the same way again. `tests/testthat/
test-serve.R`'s mocked suite could not have caught this on its own --
the fake `processx::process` stub the tests use never had a real child
process to leak in the first place, only `tests/testthat/
test-wiring.R`'s real end-to-end block (a genuine subprocess, genuinely
killed and re-checked) would have, and even that only if it happened to
restart a server at the same port after stopping one, which it didn't
do before this fix.

**Every schema document requires an explicit `deckifyr:` version field
(spec §7.1), checked by one shared validator.**
`deckifyr.schema.version.check_schema_version()` is reused by all three
document models specifically so the supported-version set only needs
updating in one place as the schema evolves -- don't duplicate a
version check per model.

**`pyro` (and any other r-universe-only dependency) needs
`options(repos=)` to include `a2-ai.r-universe.dev`, and getting there
took three attempts against real CI/clean-sandbox failures -- two
plausible-looking fixes verifiably do not work.** quartifyr's CI adds
that repo via the `RENV_CONFIG_REPOS_OVERRIDE` env var, but that's
renv-specific; this repo's `full-pipeline` job (`ci.yml`) resolves deps
via `pak` (`r-lib/actions/setup-r-dependencies`), which never reads it
-- first attempt, failed on the first real push. DESCRIPTION's
`Additional_repositories:` field looked like the fix next (it's the
standard mechanism CRAN policy and `remotes::install_deps()` use for
exactly this), but `pak`'s `deps::.` local solve doesn't consult it
either -- confirmed in CI a second time. **The trap in "confirming"
either of these locally**: `pak` treats an already-installed package as
satisfying a dependency regardless of what's in `options(repos=)`, so
testing on a machine that already has `pyro` installed (true of this
repo's own dev environment) makes broken repo config look like it
works. The real test needs `pak::lockfile_create(..., lib =
"<empty-dir>")` to force a genuine repo resolution. The actual, verified
fix is this repo's root **`.Rprofile`**, which sets `options(repos=)`
directly and is sourced automatically by every plain `Rscript` step
(including `setup-r-dependencies`'s own) run from the repo root --
confirmed against a clean-lib sandbox before it went into CI. `pyro` is
deliberately *not* listed as an `any::pyro` extra package in `ci.yml`;
it only needs to be resolvable via `deps::.` (DESCRIPTION's `Imports:`),
same as any other real dependency.

`R-CMD-check.yaml`/`test-coverage.yaml` (the standard r-lib workflows,
modeled on quartifyr's own versions of the same two files) use a
*different* mechanism for the same problem: an explicit step that reads
DESCRIPTION's `Additional_repositories` field and appends an
`options(repos=)` line to `~/.Rprofile` (the runner's home profile, not
this repo's root one). This isn't redundant with the root `.Rprofile`
above by mistake -- quartifyr's own two standard workflows carry the
identical step despite that repo also having a root `.Rprofile`,
so don't assume the repo-root file alone is sufficient for every
job/OS combination `check-r-package`'s composite action steps run
under; keep both mechanisms in sync with `Additional_repositories`
rather than trying to consolidate them into one.

**`deckifyr.renderers.quarto` is real (see this file's own "Quarto
integration" section below) but still honors spec §20 warning 2's
separate caution -- it never uses Quarto's own PPTX/presentation writer
as the compositor; `deckifyr.pptx.compose` places Quarto's output
exactly like any other resolved element.** (`deckifyr.web` was the last
package in this repo actually matching the "intentionally empty
docstring-only package, spec §20 warning 5's caution against building
it early" description this note used to make about it -- see this
file's own "Web application" section above for what it is now.)

**Reference-PPTX support is descoped, not deferred (spec §10.1/§21,
decided): `deckifyr.pptx.compose` always uses `python-pptx`'s own
bundled default template, never a project-supplied reference file.**
Every `deckifyr build` starts from `pptx.Presentation()` with no
arguments, overrides `slide_width`/`slide_height` from `design.yaml`,
and adds every slide against that template's "Blank" native layout
(found by name, spec §10.1's "known blank or minimal native layout").
This was considered and rejected as a v1 feature, not left as a gap: no
element deckifyr composes inherits color or font from a native theme --
every style comes from `design.yaml` tokens (§7.4) and, for branding, the
`furniture` block (§7.8) -- so a project-supplied `.pptx` would add
nothing but a binary, non-diffable artifact back into a pipeline whose
whole premise is replacing exactly that (see this file's "What this
is"). Don't add a `--reference-pptx` flag, a `design.yaml` field for one,
or any code path reading a template from disk in `deckifyr.pptx` --
that idea was explicitly ruled out, not just unbuilt.

**`deckifyr.plan` (Pass 1) and `deckifyr.pptx.compose` (Pass 2) stay
genuinely decoupled: `deckifyr.plan` has zero `python-pptx` import.**
This isn't just tidiness -- spec §6 keeps the two passes separate
specifically so a shell (the output of `expand_presentation`) can be
inspected or cached independent of whatever consumes it, and today's
`ResolvedElement`/`ResolvedSlide` dataclasses in `deckifyr/plan.py` are
that shell. Style tokens (`design.fonts`/`design.colors`) are resolved
to literal values during planning, not composition, for the same
reason: a `ResolvedElement` should be usable without `design.yaml` in
hand a second time. If you're adding a new element type, its
`SUPPORTED_ELEMENT_TYPES` membership and any zone/required semantics
belong in `deckifyr/plan.py`; only the actual `python-pptx` shape
construction belongs in `deckifyr/pptx/compose.py`.

**Three separate CI workflows cover R, on purpose, mirroring quartifyr's
own split (see its CLAUDE.md).** `.github/workflows/ci.yml`'s
`full-pipeline` job is the real R -> pyro -> Python integration proof:
it runs directly against this checkout (after `uv sync --extra dev`
provisions `.venv/`), so `tests/testthat/test-wiring.R`'s pyro-dependent
tests actually execute. `.github/workflows/R-CMD-check.yaml` and
`test-coverage.yaml` are the standard, largely unmodified r-lib
templates (`r-lib/actions/check-r-package`, `r-lib/actions/
test-coverage`) -- they validate package structure/documentation/
NAMESPACE and produce coverage numbers, but both install the package
into a *fresh, separate copy* and run `tests/testthat.R` against
that copy, which has no `.venv/` (correctly excluded from the package
by `.Rbuildignore`). `test-wiring.R`'s pyro-dependent tests therefore
skip cleanly under both -- confirmed locally, and this is expected
behavior, not a gap to engineer around with an env var pointing them
back at this checkout. Don't add one; that was tried and reverted (see
git history around the `R-CMD-check.yaml`/`test-coverage.yaml`
introduction) specifically because `full-pipeline` already covers real
integration, and a venv-forcing hack only complicates the standard
workflows for no real benefit -- coverage numbers being lower because
of this is honest, not a problem to hide.

**Config/slide editing (`deckifyr.editor`, CLI `get`/`set`/`slide`, the
`deck_get_config()`/`deck_set_config()`/`deck_*_slide()` R family, issue
#10) is real, tested, and follows the same "mechanism in its own module,
orchestration in `cli.py`" split `deckifyr.plan`/`deckifyr.pptx.compose`
already established.** `deckifyr/editor.py` only ever touches plain
`dict`/`list` data (whatever `yaml.safe_load` returns) -- never a
`pydantic` model, never a filesystem path -- and provides two
independent capabilities: a small dotted-path get/set accessor
(`get_value`/`set_value`, `.`/`[N]` syntax, e.g. `colors.primary` or
`slides[0].notes`) usable against any of the three document shapes, and
slide CRUD (`list_slides`/`add_slide`/`remove_slide`/`update_slide`/
`move_slide`) scoped to `presentation.yaml`'s own `slides` list, id-keyed
throughout per spec §7.6's "Array indices should never be the primary
override mechanism." `deckifyr.cli` owns every actual file read/write:
it validates the edited dict against the right `deckifyr.schema` model
(and, for a changed `slide.layout`, cross-checks it against a readable
sibling `layouts.yaml`, mirroring `_load_project`'s own check) *before*
calling `_write_yaml` -- confirmed by test
(`test_set_rejects_an_edit_that_breaks_schema_validation`,
`test_set_rejects_edit_that_introduces_a_dangling_layout_reference`) that
a rejected edit never touches the file on disk. `_write_yaml` itself
writes to a sibling `.tmp` file and renames it into place
(`Path.replace`, i.e. `os.replace`) so a mid-write crash can't leave a
half-written config behind, and dumps with `sort_keys=False` to keep the
mapping key order a human actually wrote (Python dicts are
order-preserving; PyYAML respects that when told not to re-sort) --
comments are not preserved on a round trip through `get`/`set`/`slide`
(plain PyYAML, not `ruamel.yaml`, to avoid a second YAML-library
dependency across both facades for a v1 feature), which is a real,
accepted limitation, not an oversight.

**`set`'s value parser is JSON, not YAML -- confirmed the hard way, not
a stylistic choice.** The obvious first design was "parse the CLI's
`value` argument the same way the file itself is parsed, with
`yaml.safe_load`" -- tried, and it silently breaks on the single most
common kind of value this command exists to write: `design.yaml`'s own
hex colors. `#` opens a YAML comment, so `yaml.safe_load("#123456")`
doesn't error, it quietly returns `None` -- caught only by actually
running `deckifyr set design.yaml colors.primary "#123456"` by hand
while smoke-testing this feature, not by reasoning about it in advance
(now pinned down as a regression test,
`test_set_writes_a_hex_color_without_quoting`). `deckifyr.cli
._parse_set_value` uses `json.loads` instead: JSON has no comment
syntax at all, so it either parses `value` unambiguously as a
number/bool/null/array/object (the same vocabulary `--elements-json`
already uses) or raises -- at which point `value` was never valid JSON
to begin with, so it's used as a literal string. An ordinary bare
word/hex color/font name therefore needs no quoting on the command line,
while `true`/`null`/`[1, 2]`/`'"12pt"'` still parse as their typed
values when a caller actually wants that; `--string` forces the literal-
string branch for the rare case a value would otherwise parse as
something else (writing the literal text `"true"`, say).

**`update_slide`'s `layout`/`notes` keyword arguments needed a sentinel,
not `None`, for "leave this field alone" -- `Slide.layout: null`
(freeform) and "no notes" are both meaningful, valid values in their own
right (spec §7.6), so `None` can't double as both "unset this field" and
"I didn't pass this argument."** `deckifyr.editor.UNSET` is that
sentinel on the Python side; the R wrappers
(`deck_update_slide()`/`R/slides.R`) face the identical problem one
layer up and solve it the same shape of way but with R's own idiom
instead of a sentinel object: `NULL` (R's natural "leave alone" default)
stays "leave alone", and `NA` -- otherwise unused here -- means "clear
this field" (`--no-layout`/`--clear-notes`), rather than reusing `NULL`
for both meanings the way an R function normally would.

**`R/slides.R`/`R/config.R` add `cli` as a real `Imports:` dependency
(previously used transitively via `devtools`/`roxygen2` in this repo's
own dev environment, never declared as a package dependency) -- every
`deck_*_slide()`/`deck_set_config()` call reports success via
`cli::cli_alert_success()`/`cli::cli_h3()`/`cli::cli_li()`, per issue
#10's own ask ("make use of the cli package for nice output"). `cli` is
lightweight and has no r-universe-only dependency of its own, so this
needed no `Additional_repositories`/`.Rprofile` changes (contrast
`pyro`'s own repo-resolution story earlier in this file) -- just adding
it to `DESCRIPTION`'s `Imports:` and re-running `roxygen2::roxygenise()`.
`.placement_args()` (shared by `deck_add_slide()`/`deck_move_slide()`)
is the one piece of real argument validation done in R rather than
delegated to Python -- rejecting more than one of `after`/`before`/
`index` before ever shelling out, per spec §11.2's "Validate arguments
in R when inexpensive"; `deckifyr.editor.AmbiguousPlacementError` and
argparse's own mutually-exclusive-group check on the Python/CLI side
still exist too, as defense in depth for any caller that reaches
`deckifyr.editor`/the CLI directly rather than through these R wrappers.

**Every new `@export`ed R function must be added to `_pkgdown.yml`'s own
`reference:` index, in the same PR that adds the function -- confirmed
the hard way: issue #10's first merge to `main` broke the live docs
site.** `_pkgdown.yml`'s `reference:` block is a hand-maintained,
complete list of exported topics grouped into sections; `pkgdown::
build_site()` hard-*errors* (`"N topics missing from index"`), not just
warns, when an exported `Rd` topic isn't listed anywhere in it, and
`.github/workflows/pages.yml` runs `pkgdown::build_site()` after every
push to `main` (triggered by `release.yaml`'s own completion via
`workflow_run` -- see that workflow's own header comment for why a plain
`push` trigger doesn't work here: it would deploy the site from
DESCRIPTION/NEWS.md as they stood *before* release.yaml's own
"chore: sync release metadata" commit, and never redeploy after that
commit lands) with no dry-run gate -- so a missed entry doesn't fail the
PR itself (R CMD check/pytest/covr don't touch `_pkgdown.yml` at all), it
silently breaks the live docs deploy right after merge, discovered only
by noticing the Pages workflow's red X. Before opening a PR that adds an
`@export`, actually run
`Rscript -e 'pkgdown::build_site(new_process = FALSE, install = FALSE, preview = FALSE)'`
against a real `R CMD INSTALL`ed copy of the package (not just
`devtools::load_all()`, which `pkgdown` doesn't use) -- see
CONTRIBUTING.md's own copy of this same check.

**`DESCRIPTION`'s `Version:` field is not hand-edited -- it's
bot-managed, derived from the repo-root `VERSION` file by
`.github/workflows/release.yaml`'s `sync-release-metadata.R` step on
every push to `main`, and any manual edit gets silently overwritten on
the next push.** Confirmed directly: a manual `Version: 0.1.1` bump in
DESCRIPTION during issue #10's work was reverted back to `0.1.0` by an
automated `chore: sync release metadata for 0.1.0` commit, since
`VERSION` itself hadn't changed (`sync-release-metadata.R` compares
`VERSION` against the latest released git tag, not against whatever
DESCRIPTION currently says). To actually bump the release version, edit
`VERSION` (and let the workflow fold the `NEWS.md` "(development
version)" section into a new dated heading) -- never edit
`DESCRIPTION`'s `Version:` directly, even when asked to "bump the
patch version"; that request means `VERSION`, not `DESCRIPTION`.

## Testing strategy

Today's tests are unit-level plus two kinds of true integration test:
`tests/python/` covers units/merge/schema/CLI exit codes in isolation,
plus `test_plan.py` (layout/slide expansion), `test_pptx.py` (fit-mode
geometry, manifest shape, opening the written `.pptx` back up with
`python-pptx` to check slide/shape counts and names), `test_editor.py`
(dotted-path get/set and slide-CRUD edge cases against plain dicts, no
CLI/filesystem involved), and `test_cli_editing.py` (the `get`/`set`/
`slide` subcommands end to end against real files in `tmp_path`,
including the JSON-vs-YAML value-parsing regression and the
validate-before-write guarantee -- see this file's own config/slide-
editing architecture note above);
`tests/testthat/test-wiring.R` is the only test that actually invokes
the real R -> pyro -> Python bridge (the other two R-side gotchas above
were both caught by *running* this test against a live toolchain, not
by reasoning about the code) -- its own last `test_that()` block does
the same for `deck_get_config()`/`deck_set_config()`/the `deck_*_slide()`
family, while `tests/testthat/test-config.R`/`test-slides.R` cover their
arg-assembly logic with `.run_deckifyr_cli()` mocked, the same split
`test-build.R`/`test-validate.R` already established. `test_renderers_quarto.py`/
`test_resolvers_quarto.py`/the end-to-end tests in `test_pptx_quarto.py`
are the second kind: real integration tests against a live `quarto`
binary (Typst rendering, R-chunk execution, timeout/output-size
enforcement all included), skipping cleanly when `quarto` isn't on
`PATH` the same way `test-wiring.R` skips without uv/pyro -- see this
file's "Quarto integration" architecture note above. `test_renderers_preview.py`
(a real `render_slide_previews()` call against a real `soffice` binary,
skipping cleanly when it's absent) and `test_cli.py`'s `inspect`/
`preview` tests (the `preview` one also gated on `soffice`; `inspect`'s
own tests need nothing external and always run) are the same pattern
applied to "Preview rendering" above; `tests/testthat/test-run-python.R`
covers `.handle_missing_dependency()`/`.homebrew_cask_for_dependency()`
directly (asserting the non-interactive fallback path specifically,
since `interactive()` is always `FALSE` under `testthat` -- see that
architecture note's own last sentence). What's still missing from spec
§17's later
categories: real visual-regression testing (rendering a slide to an
image and diffing it) and broader OOXML structural validation beyond
shape names/counts -- today's PPTX tests check what `python-pptx` can
read back, not what the file looks like rendered or its full
relationship-graph integrity.
