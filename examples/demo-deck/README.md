# deckifyr demo deck

A small, working example, in the spirit of
[quartifyr's `examples/demo-report`](https://github.com/jprybylski/quartifyr/tree/main/examples/demo-report):
a four-slide PK-style deck built from version-controlled YAML, using a
real `reportifyr` artifact rather than placeholder content.

## What it builds

1. **Title** -- a markdown heading + italic subtitle (`layout: blank`,
   list-form elements).
2. **Concentration-Time Profile** -- a two-zone `plot-with-note` layout
   (defined in `layouts.yaml`, not `title-content`): the figure on the
   left, an interpretive note on the right, matching the `exposure-plot`
   slide shape in `deckifyr-specification.md` section 7.6's own example.
   Also carries speaker notes (`notes:`), the only slide in this deck
   that does.
3. **Per-Subject PK Summary** -- a `table` element (`layout: blank`,
   list-form elements) rendered from `OUTPUTS/tables/pk-summary.csv` as
   a native, fully-editable PowerPoint table, exercising
   `deckifyr.resolvers.TableResolver` (spec section 9.2).
4. **Closing** -- a freeform (`layout: null`) slide combining text, a
   markdown note, and a rotated logo image, to exercise `z_index` and
   `rotation` together.

## Where the figure comes from

`OUTPUTS/figures/conc-time.png` (and its reportifyr metadata sidecar,
`conc-time_png_metadata.json`, kept alongside it for provenance even
though nothing here reads it yet) are copied straight from
[quartifyr's `examples/demo-report/scripts/01_analysis.R`](https://github.com/jprybylski/quartifyr/blob/main/examples/demo-report/scripts/01_analysis.R)
-- the same run that generates the concentration-time figure that
report's own `.qmd` fills via a `{rpfy}:conc-time.png` magic string. Base
R's built-in `Theoph` dataset (12 participants' theophylline serum
concentrations after a single oral dose) is the underlying data in both
places. `assets/logo.png` is likewise copied from that same demo
project's `assets/`.

**This deck references that PNG as a plain local file, not a `{rpfy}:`
reference.** `deckifyr.resolvers`' reportifyr magic-string resolver
(spec section 9) isn't implemented yet -- see `CLAUDE.md`'s status
table -- so `concentration-time`'s `figure` element uses
`source: OUTPUTS/figures/conc-time.png`, resolved by the plain
`LocalFileResolver` that *is* implemented. Once the reportifyr resolver
lands (Phase 2), the only change needed here is that one `source:` value
becoming `source: "{rpfy}:conc-time.png"`; everything else -- geometry,
fit mode, alt text, the rest of the deck -- stays as-is.

## Where the table comes from

`OUTPUTS/tables/pk-summary.csv` is a per-subject summary (weight, dose,
observed peak concentration `Cmax`, and time-to-peak `Tmax`) computed
from the same base-R `Theoph` dataset as the concentration-time figure
above -- one row per participant, derived with `max()`/`which.max()`
over each subject's observed profile rather than any PK modeling. The
`pk-summary` slide's `pk-table` element resolves it with
`deckifyr.resolvers.TableResolver` (CSV support is built in; the same
resolver also reads `.parquet`, via the optional `pyarrow` extra) into a
native, fully-editable PowerPoint table -- first row as header, `style:
footnote` keeping thirteen rows legible in the slide's box.

## Building it

```bash
uv run deckifyr build examples/demo-deck/presentation.yaml
```

writes `examples/demo-deck/build/demo-deck.pptx` and
`examples/demo-deck/build/demo-deck.manifest.json` (both gitignored --
regenerate rather than expect them to already be there after a clone).

From R:

```r
deck_build("examples/demo-deck/presentation.yaml")
```

## Regenerating the source figure

If you want to regenerate `conc-time.png` from scratch rather than trust
the committed copy, run quartifyr's own
`examples/demo-report/scripts/01_analysis.R` (see that repo's README)
and copy `OUTPUTS/figures/conc-time.png` (plus its `_metadata.json`
sidecar) back into this directory's `OUTPUTS/figures/`.
