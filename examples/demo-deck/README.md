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
   `deckifyr.resolvers.TableResolver` (spec section 9.2) and, for its
   fill/border colors, a `design.yaml` `table_styles` entry.
4. **Closing** -- a freeform (`layout: null`) slide combining text, a
   markdown note, and a rotated logo image, to exercise `z_index` and
   `rotation` together.

## Where the figure comes from

`OUTPUTS/figures/conc-time.png` and its reportifyr metadata sidecar,
`conc-time_png_metadata.json`, are copied straight from
[quartifyr's `examples/demo-report/scripts/01_analysis.R`](https://github.com/jprybylski/quartifyr/blob/main/examples/demo-report/scripts/01_analysis.R)
-- the same run that generates the concentration-time figure that
report's own `.qmd` fills via a `{rpfy}:conc-time.png` magic string. Base
R's built-in `Theoph` dataset (12 participants' theophylline serum
concentrations after a single oral dose) is the underlying data in both
places. `assets/logo.png` is likewise copied from that same demo
project's `assets/`.

**This deck resolves that figure through a real `{rpfy}:conc-time.png`
reference**, not a plain local file: `concentration-time`'s `figure`
element uses `type: reportifyr`, `value: "{rpfy}:conc-time.png"`,
resolved by `deckifyr.resolvers.ReportifyrResolver` (spec section 9)
against `OUTPUTS/figures/` and that metadata sidecar. The sidecar's
`meta_type` (`conc-time-trajectories`) and `abbreviations` (`PK`) are
looked up in this directory's own `standard_footnotes.yaml` -- a
two-entry excerpt of reportifyr's own bundled file -- to build a footer
placed beneath the figure by default
(`footer_placement: below`, `design.yaml`'s `defaults.footer_style:
footnote`). `presentation.yaml`'s `build.reportifyr.standard_footnotes`
points at that file; without it, a `{rpfy}:`-sourced element with a
footer to show fails the build with a clear error rather than silently
skipping it.

## Where the table comes from

`OUTPUTS/tables/pk-summary.csv` is a per-subject summary (weight, dose,
observed peak concentration `Cmax`, and time-to-peak `Tmax`) computed
from the same base-R `Theoph` dataset as the concentration-time figure
above -- one row per participant, derived with `max()`/`which.max()`
over each subject's observed profile rather than any PK modeling. The
`pk-summary` slide's `pk-table` element resolves it with
`deckifyr.resolvers.TableResolver` (CSV support is built in; the same
resolver also reads `.parquet`, via the optional `pyarrow` extra) into a
native, fully-editable PowerPoint table -- first row as header. Its
typography comes from `style: table-body`, a `text_styles` entry of its
own (13pt/`text`) rather than the shared `footnote` style branding/
page-number furniture and the reportifyr footer use -- bumping this
table's font size doesn't touch theirs. Its fill/border chrome (blue
header band, alternating row tint, thin gray grid lines) comes from
`table_style: pk-summary`, a `design.yaml` `table_styles` entry
exercising the deck's own brand colors (`primary`/`muted`) rather than
`python-pptx`'s bundled default table look.

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
