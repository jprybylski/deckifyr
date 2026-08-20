---
name: deckifyr-presentation
description: Author or edit a deckifyr presentation.yaml — a deck's slide order, content, and build settings, referencing an existing design.yaml (Style) and layouts.yaml (Layout). Use when adding/removing/reordering slides, adding elements (text, markdown, image, table, shape, group, reportifyr artifact, or quarto fragment) to a slide, setting speaker notes, or configuring the deck's watermark/status indicator or build output.
---

# deckifyr presentation.yaml: slide content

deckifyr (https://github.com/A2-ai/deckifyr) compiles `.pptx` decks from
`presentation.yaml` plus the `design.yaml`/`layouts.yaml` pair it
references. This skill covers authoring `presentation.yaml` itself — a
deck's slide order and per-slide content. If `design.yaml`/`layouts.yaml`
don't exist yet, or need new design tokens or layout zones first, use the
`deckifyr-org-config` skill before this one.

## Get the authoritative field list first

Don't rely on this skill's own examples as an exhaustive field reference
— run this before writing or editing the file:

```bash
deckifyr schema presentation
```

Prints the live JSON Schema, generated from deckifyr's own pydantic
model, always current. R equivalent: `deck_schema("presentation")`.

## Mental model

- `deckifyr: "0.1"` version key, `design: {base: design.yaml}`,
  `layouts: layouts.yaml`, `metadata` (title/author/status), and a `build`
  block (`output`, `manifest`, `strict`, `previews`) at the top level.
- `slides` is an **ordered list**, each entry a dict with a stable `id`
  (used for CLI/API targeting and diagnostics — never rely on a slide's
  position alone), a `layout` (a name from `layouts.yaml`, or `null` for
  no fixed zones), and `elements`. If the layout defines named zones,
  `elements` is a dict keyed by zone id whose values *override* that
  zone (commonly just `value:`/`source:` — the zone already supplies
  `type`/`box`/`style`). If the slide has `layout: null` (or needs
  elements the layout doesn't define), `elements` is a list of full
  element definitions, each with its own `id`.
- Supported element `type`s: `text`, `markdown`, `image`, `shape`,
  `group` (nests other elements, still using slide-absolute geometry —
  not group-relative coordinates), `table` (source is a `.csv`/`.parquet`
  file; first row is the header), `reportifyr` (resolves a `{rpfy}:...`
  magic-string reference to a reportifyr artifact, with an optional
  metadata-derived footer), and `quarto` (executes a `.qmd` fragment;
  `render_mode: native` reuses text rendering, `png` rasterizes via
  Typst — `svg` is not supported as an auto/compositor mode).
- Common per-element fields: `box` (`{x, y, width, height}`, all
  units-explicit like `0.75in`/`18pt`), `rotation` (clockwise degrees),
  `z_index`, `style` (a `design.yaml` `text_styles`/`table_styles` name),
  `fit` (`contain`/`cover`/`stretch`/`none`, images/quarto png), `overflow`
  (`error`/`shrink`/`clip`/`continue`), `alt_text`, `required` (fail the
  build if unresolved/empty), `center`/`align` (text/markdown vertical
  centering and horizontal alignment within `box`).
- A slide's own `notes` field (plain string, not an element) becomes the
  native PowerPoint speaker-notes page.
- The deck-wide watermark/status marker is two fields working together:
  `status_indicator` (`watermark` / `corner-tr` / `corner-tl` /
  `corner-bl` / `corner-br` / `none`) picks *which* `design.yaml`
  furniture placement shows, and its text is `metadata.status` by
  default — set the top-level `watermark:` field only when the mark's
  text should differ from `metadata.status`. Both fields belong here in
  `presentation.yaml`; the placement's own style/box/rotation is defined
  in `design.yaml` (the `deckifyr-org-config` skill) and must already
  exist there, or `deckifyr validate` will reject an unconfigured
  placement.

## Worked example

```yaml
slides:
  - id: title
    layout: blank
    elements:
      - id: deck-title
        type: markdown
        value: "# Deck Title"
        box: {x: 0.9in, y: 2.1in, width: 11.5in, height: 1.1in}
        render_mode: native
        style: title

  - id: exposure-plot
    layout: title-content        # a layout with named `title`/`content` zones
    elements:
      title:
        value: A slide using the title-content layout
      content:
        type: reportifyr
        value: "{rpfy}:01-12345-pk-timecourse.png"
        fit: contain
        alt_text: Concentration-time profiles by treatment group
```

Point-and-shoot starting file: `deckifyr init <directory>` scaffolds a
working `presentation.yaml` alongside its `design.yaml`/`layouts.yaml`;
the package's own `inst/examples/minimal-deck/presentation.yaml` and the
richer `examples/demo-deck/presentation.yaml` (tables, groups, a
reportifyr figure with a real footer, a Quarto fragment) are readable
worked examples if a local checkout of deckifyr is available.

## Validate, build, and preview — don't guess at correctness

```bash
deckifyr validate presentation.yaml            # schema + geometry + reference checks
deckifyr --json validate presentation.yaml      # structured errors
deckifyr build presentation.yaml                # writes the .pptx + manifest
deckifyr preview presentation.yaml              # renders each slide to PNG (needs LibreOffice on PATH)
deckifyr inspect presentation.yaml              # reports the resolved slide/element plan, no side effects
```

Run `validate` after every edit and fix what it reports before assuming
a change is correct — element type/field rules, required-zone
enforcement, and geometry bounds are all real, current schema rules, not
something to infer from an old example. `preview`/`build.previews: true`
need a local LibreOffice (`soffice`) install; a missing dependency is
reported as a distinct, clearly-labeled error rather than a generic
failure.

## Small, targeted edits

For a single change rather than a hand-edit, prefer the `slide`/`get`/
`set` subcommands — they validate before writing, so a rejected edit
never corrupts the file on disk:

```bash
deckifyr slide list presentation.yaml
deckifyr slide add presentation.yaml --id new-slide --layout blank --after title
deckifyr slide update presentation.yaml new-slide --notes "Updated speaker notes"
deckifyr slide move presentation.yaml new-slide --index 0
deckifyr slide remove presentation.yaml new-slide
deckifyr get presentation.yaml slides[0].notes
deckifyr set presentation.yaml metadata.status "final"
```

R equivalents follow the same names: `deck_list_slides()`,
`deck_add_slide()`, `deck_update_slide()`, `deck_move_slide()`,
`deck_remove_slide()`, `deck_get_config()`, `deck_set_config()`.
