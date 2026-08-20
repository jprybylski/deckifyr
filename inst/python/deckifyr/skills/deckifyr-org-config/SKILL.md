---
name: deckifyr-org-config
description: Author or edit a deckifyr design.yaml (Style) and layouts.yaml (Layout) — the org-level configuration shared by every deck. Use when creating a new deckifyr organization/project template, adding or changing design tokens (colors, fonts, text/shape/table styles, gradients, document furniture), or adding/editing a reusable slide layout's named zones.
---

# deckifyr org-level config: design.yaml + layouts.yaml

deckifyr (https://github.com/A2-ai/deckifyr) compiles `.pptx` decks from
three version-controlled YAML documents instead of a hand-clicked
PowerPoint template. This skill covers the two **org-level** documents
that are shared by every deck built against them — `design.yaml` (the
Style: typography, colors, spacing, chrome) and `layouts.yaml` (the
Layout: reusable, named slide structures). A deck's own per-slide content
lives in `presentation.yaml`, which is a different skill
(`deckifyr-presentation`) — don't put slide content here.

## Get the authoritative field list first

Field names, types, and constraints for these two documents change as
deckifyr evolves; don't rely on this skill's own examples as an exhaustive
reference. Before writing or editing either file, run:

```bash
deckifyr schema design
deckifyr schema layouts
```

Each prints the live JSON Schema for that document, generated straight
from deckifyr's own pydantic models — this is always current, unlike a
hand-maintained field list. If a project has an R environment instead,
the equivalent is `deck_schema("design")` / `deck_schema("layouts")`.

## Mental model

- Every document starts with an explicit `deckifyr: "0.1"` version key.
- **`design.yaml`** defines: `slide` (width/height/background, optionally
  `background_gradient`, `safe_area`), `fonts` (named font roles like
  `body`/`heading`/`monospace`), `colors` (named tokens — a value is
  either a literal hex string or a **derivation**: `{base: <token>,
  lighten|darken|saturate|desaturate: 0.0-1.0}` or `{base: <token>, mix:
  <token>, weight: 0.0-1.0}`, chainable, computed at build time),
  `text_styles`/`shape_styles`/`table_styles` (named, reusable chrome —
  referenced by name from `layouts.yaml`/`presentation.yaml`, never
  inlined per-element), `defaults` (project-wide fallbacks like
  `overflow`/`image_fit`/`rotation`), and `furniture` (background image,
  status/watermark placements, branding, page numbers — see "Document
  furniture" below).
- **`layouts.yaml`** defines named `layouts`, each a set of **named**
  `elements` (a dict keyed by element id, not a list) with a `type`
  (`text`, `slot`, `footnotes`, or any content type), a `box`
  (`{x, y, width, height}`, absolute in slide units), and optionally
  `style`/`required`. A layout with `elements: {}` (conventionally named
  `blank`) is the common "no fixed zones" escape hatch a presentation
  slide can still opt into.
- Everything is **units-explicit**: `0.75in`, `18pt`, `2.5cm` — never a
  bare number for a geometry field. Coordinate origin is the slide's
  top-left; positive `x` is right, positive `y` is down, positive
  rotation is clockwise.
- **Named things win over positional things.** Layout zones are a dict
  keyed by id; colors/fonts/styles are referenced by their token name.
  Never rely on YAML list order or array indices to identify a zone or a
  style — that's exactly what deckifyr's own merge model (base design <
  org override < project override < layout < slide override < element
  inline style — all dict-recursive-merge, scalars/lists replace) is
  built to avoid.
- A `colors`/`fonts`/`text_styles`/etc. field elsewhere in the schema
  accepts either a token name (looked up in `design.yaml`) or a bare
  literal (a hex string, a literal font name) — both are always valid,
  so a token isn't strictly required, but prefer tokens for anything
  reused across slides.

## Document furniture (optional, in `design.yaml`)

`furniture` is deckifyr's mechanism for chrome that appears on every
slide without being authored per-slide: a `background` image, a
`branding` text/logo element, a `page_number` (with `{page}`/`{total}`
placeholders), and `status` — up to five named placements
(`watermark`, `corner_tr`, `corner_tl`, `corner_bl`, `corner_br`), each
its own `box`/`style`/`rotation`. A deck opts into exactly one status
placement via `presentation.yaml`'s top-level `status_indicator` field
(`watermark` / `corner-tr` / `corner-tl` / `corner-bl` / `corner-br` /
`none`) — configuring a placement here doesn't show it on its own; that
belongs to the `deckifyr-presentation` skill.

## Start from a working example, then validate

Don't write either file from a blank page. Scaffold a real, valid
starting pair with:

```bash
deckifyr init <directory>
```

then edit `<directory>/design.yaml` and `<directory>/layouts.yaml`
directly, or read them without scaffolding at
`inst/examples/minimal-deck/{design,layouts}.yaml` inside the deckifyr
package itself for reference. After every edit, validate:

```bash
deckifyr validate <directory>/presentation.yaml
deckifyr --json validate <directory>/presentation.yaml   # structured errors for programmatic parsing
```

Validation resolves both `design.yaml` and `layouts.yaml` through the
presentation that references them, so run it against the presentation,
not the config file alone. Fix reported errors and re-run until it
passes — schema/geometry/reference errors are deckifyr's real, current
rules; don't guess at what's valid instead of checking.

## Small, targeted edits

For a single field change rather than a rewrite, `deckifyr set` avoids
hand-editing YAML and validates before writing (a rejected edit never
touches the file on disk):

```bash
deckifyr set design.yaml colors.primary "#2457A6"
deckifyr get design.yaml text_styles.title
```

Values are parsed as JSON when possible (so bare hex colors, unquoted
numbers, `true`/`false`/`null` all work as expected); pass `--string` to
force a literal string.
