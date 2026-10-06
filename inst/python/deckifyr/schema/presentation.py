"""Pydantic models for `presentation.yaml` (spec section 7.6).

Slide order, content references, geometry overrides, notes, and build
settings. This module only validates shape -- it does not resolve
`design.base`/`layouts` paths, merge layouts onto slides, or expand
`{rpfy}:` references; that's the plan-resolution step described in spec
section 6, not yet implemented (see the module docstring in
`deckifyr.resolvers`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deckifyr.schema.layouts import Element, StatusIndicatorMode
from deckifyr.schema.version import check_schema_version


class DesignRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str = Field(description="Path to the `design.yaml` this deck uses.")


class Metadata(BaseModel):
    # Open-ended: orgs attach arbitrary metadata fields (study id, status,
    # confidentiality, ...) beyond the ones the spec's example shows.
    model_config = ConfigDict(extra="allow")

    title: str = Field(description="Presentation title.")
    author: str | None = Field(None, description="Presentation author.")
    # Free text ("draft", "demo", "final", ...) -- also the default
    # status-indicator text (spec section 7.8) when `PresentationDocument
    # .watermark` is unset (`deckifyr.plan.expand_presentation`), so a
    # deck doesn't need the same word typed in two places.
    status: str | None = Field(
        None,
        description=(
            "Free-text status such as draft or final; also the default status-mark "
            "text."
        ),
    )


class FlextableConfig(BaseModel):
    """Execution settings for rendering a reportifyr `.rds` artifact --
    an R `flextable` object (issue #57) -- to a picture via
    `deckifyr.renderers.flextable`. Nested under `ReportifyrConfig`
    rather than a `QuartoConfig`/`PreviewConfig`-style top-level
    `BuildConfig` sibling: unlike Quarto/preview rendering (each
    triggered by its own distinct element type), flextable rendering
    only ever exists to serve a `reportifyr` element whose resolved
    artifact happens to be `.rds`. `None` on `ReportifyrConfig.flextable`
    (the default) means every setting below's own default -- read
    lazily by `deckifyr.pptx.compose._build_reportifyr_context`, only
    when a build actually resolves an `.rds` reportifyr artifact.
    """

    model_config = ConfigDict(extra="forbid")

    # The `Rscript` binary to invoke -- a bare name resolved via PATH by
    # default, or a full path for a non-PATH install.
    binary: str = Field(
        "Rscript",
        description="The `Rscript` binary: a bare name looked up on PATH, or a full path.",
    )
    timeout_seconds: float = Field(60, description="Give up on a render after this many seconds.")
    max_output_bytes: int = Field(
        5_000_000,
        description="Reject a rendered picture larger than this.",
    )
    # Maps to `flextable::save_as_image()`'s own `res=` (resolution in
    # DPI) -- 200 matches that function's own default.
    dpi: int = Field(200, description="Render resolution in dots per inch.")


class ReportifyrConfig(BaseModel):
    """Where/how to resolve `{rpfy}:` magic strings (spec section 9.1),
    project-relative paths. `standard_footnotes` is required only
    lazily -- a build with no `reportifyr`/rpfy-sourced element never
    reads it; `deckifyr.pptx.compose` raises a `ContentValidationError`
    if one exists and this is unset.
    """

    model_config = ConfigDict(extra="forbid")

    outputs_dir: str = Field(
        "OUTPUTS",
        description="Project-relative folder searched recursively for `{rpfy}:` artifacts.",
    )
    standard_footnotes: str | None = Field(
        None,
        description=(
            "Project-relative `standard_footnotes.yaml`; only read once an element "
            "needs a footer."
        ),
    )
    # Mirrors reportifyr's own `add_footnotes()` R parameter of the same
    # name and default -- reportifyr has no `config.yaml`-level
    # equivalent (it's a call-time argument there too), so this is
    # deckifyr's own project-level home for the same choice.
    fail_on_missing_metadata: bool = Field(
        True,
        description="Fail the build when an artifact has no metadata sidecar.",
    )
    # Rendering settings for `.rds` flextable artifacts (issue #57) --
    # see `FlextableConfig`'s own docstring for why this lives here
    # rather than as a `BuildConfig` sibling.
    flextable: FlextableConfig | None = Field(
        None,
        description=(
            "Settings for rendering `.rds` flextable artifacts; unset uses the "
            "defaults."
        ),
    )


class QuartoConfig(BaseModel):
    """Execution settings for `type: quarto` elements (spec section 8.1,
    issue #3), project-relative to `presentation.yaml` where a path is
    involved. `None` on `BuildConfig.quarto` (the default) means every
    setting below's own default -- read lazily by
    `deckifyr.pptx.compose`'s `_build_quarto_context`, only when a build
    actually contains a `quarto` element, same as `ReportifyrConfig`.
    """

    model_config = ConfigDict(extra="forbid")

    # The `quarto` binary to invoke -- a bare name resolved via PATH by
    # default, or a full path for a non-PATH install.
    binary: str = Field(
        "quarto",
        description="The `quarto` binary: a bare name looked up on PATH, or a full path.",
    )
    timeout_seconds: float = Field(60, description="Give up on a render after this many seconds.")
    max_output_bytes: int = Field(
        5_000_000,
        description="Reject rendered output larger than this.",
    )


class PreviewConfig(BaseModel):
    """Tuning knobs for slide preview rendering (spec section 12/18 Phase
    3), mirroring `QuartoConfig`'s own "`None` means every default
    applies" shape -- `previews: true` below is the on/off switch; this
    block only matters once that (or an explicit `deckifyr preview`
    invocation) actually triggers a render.
    `deckifyr.renderers.preview.render_slide_previews` shells out to
    LibreOffice for real PowerPoint-engine fidelity, so `binary` is a
    bare name resolved via PATH by default, or a full path for a
    non-PATH install -- same convention as `QuartoConfig.binary`.
    """

    model_config = ConfigDict(extra="forbid")

    binary: str = Field(
        "soffice",
        description=(
            "The LibreOffice `soffice` binary: a bare name looked up on PATH, or a "
            "full path."
        ),
    )
    dpi: int = Field(110, description="Preview image resolution in dots per inch.")
    timeout_seconds: float = Field(
        120,
        description="Give up on a preview render after this many seconds.",
    )


class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strict: bool = Field(
        True,
        description="Reject unitless geometry and other loosely specified values.",
    )
    output: str = Field(description="Where the built `.pptx` is written.")
    manifest: str | None = Field(None, description="Where the build manifest JSON is written.")
    # Whether `deckifyr build` also renders a PNG per slide alongside the
    # `.pptx` (spec section 7.6's own example) -- `deckifyr preview`
    # (spec section 11.1) always renders previews regardless of this
    # flag; this only controls whether an ordinary `build` does too.
    previews: bool = Field(
        False,
        description="Also render a PNG per slide, plus a PDF, with every build.",
    )
    # `deckifyr.web`'s deferred-save editor (issue #24): when `true`, every
    # edit made through the web app is flushed to disk immediately (the
    # old, always-on behavior); when `false` (the default), edits stay in
    # the running `deckifyr serve` process's in-memory working copy until
    # an explicit Save. Read/written only by `deckifyr.web.app` -- an
    # ordinary CLI `build`/`validate` never looks at this field.
    autosave: bool = Field(
        False,
        description=(
            "Web editor: write every edit to disk immediately instead of waiting for "
            "Save."
        ),
    )
    reportifyr: ReportifyrConfig | None = Field(
        None,
        description="Where and how `{rpfy}:` references are resolved.",
    )
    quarto: QuartoConfig | None = Field(None, description="How `quarto` elements are executed.")
    preview: PreviewConfig | None = Field(None, description="Tuning for slide preview rendering.")


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique slide id.")
    # `layout: null` (no layout at all, spec section 7.6's "freeform"
    # example) is a valid, distinct choice from omitting the field, so
    # this stays a required key that may hold None rather than an
    # optional-with-default field.
    layout: str | None = Field(
        description="Layout name from `layouts.yaml`, or null for a freeform slide.",
    )
    # Dict form keys elements by name to override/extend a layout's
    # named slots (spec section 7.7: "Named elements are essential.
    # Array indices should never be the primary override mechanism.");
    # list form is only for freeform slides with `layout: null`, where
    # there is no named layout to key against and each element carries
    # its own `id`.
    elements: dict[str, Element] | list[Element] = Field(
        {},
        description=(
            "Content and overrides, keyed by the layout's element ids, or a list for "
            "freeform slides."
        ),
    )
    # Speaker notes (spec section 7.1's file-responsibility table, section
    # 18 Phase 1). Plain text, not a slide element -- no box/style/z_index,
    # composed straight onto the slide's native notes page rather than
    # through the ordinary element pipeline.
    notes: str | None = Field(None, description="Speaker notes for this slide.")


class PresentationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deckifyr: str = Field(description="Schema version of this document.")
    design: DesignRef = Field(description="Which design document the deck uses.")
    layouts: str = Field(description="Path to the `layouts.yaml` this deck uses.")
    metadata: Metadata = Field(description="Title, author and status.")
    build: BuildConfig = Field(description="Output paths and build options.")
    # Which of `design.yaml`'s `furniture.status` placements (spec
    # section 7.8) this build uses -- `None` (equivalent to `"none"`,
    # the default) shows no status/watermark mark at all. Selecting a
    # placement `design.yaml` never configured a `StatusIndicatorStyle`
    # for is a build-time `ContentValidationError`
    # (`deckifyr.plan._furniture_layout`), not a silent no-op.
    status_indicator: StatusIndicatorMode | None = Field(
        None,
        description=(
            "Which status mark placement this build shows; none or unset shows "
            "nothing."
        ),
    )
    # The status/watermark mark's own text -- any word, a build-time
    # choice (spec section 7.8), not a `design.yaml` constant. `None`
    # (the default -- expected the common case) falls back to
    # `metadata.status` (`deckifyr.plan.expand_presentation`), the same
    # free-text field authors already set for descriptive purposes
    # ("draft", "demo", "final", ...), so a status/watermark mark
    # doesn't require typing the same word twice; set this explicitly
    # only when the mark's text should differ from `metadata.status`.
    # Simply unused when `status_indicator` doesn't select the watermark
    # placement (see `_check_watermark_has_text` below for the one case
    # where having neither this nor `metadata.status` is a validation
    # error rather than a quiet no-op).
    watermark: str | None = Field(
        None,
        description="Status mark text; falls back to `metadata.status` when unset.",
    )
    slides: list[Slide] = Field(description="The slides, in order.")

    _check_version = field_validator("deckifyr")(check_schema_version)

    @field_validator("slides")
    @classmethod
    def _check_unique_slide_ids(cls, slides: list[Slide]) -> list[Slide]:
        seen: set[str] = set()
        for slide in slides:
            if slide.id in seen:
                raise ValueError(f"duplicate slide id {slide.id!r}")
            seen.add(slide.id)
        return slides

    @model_validator(mode="after")
    def _check_watermark_has_text(self) -> "PresentationDocument":
        # A full-page watermark with no text would be a large, silently
        # empty rotated box -- worth failing the build over, unlike a
        # small corner placement with no text (`deckifyr.plan
        # ._furniture_layout` simply skips that one, the same "no
        # content, not required" rule an empty layout zone already
        # follows). `watermark` unset is fine as long as `metadata.status`
        # supplies the text instead (`deckifyr.plan.expand_presentation`'s
        # own fallback) -- this only fails when *neither* would give the
        # compositor anything to show.
        if (
            self.status_indicator == "watermark"
            and self.watermark is None
            and self.metadata.status is None
        ):
            raise ValueError(
                "status_indicator: watermark is active but requires either a non-null "
                "'watermark' value or a non-null 'metadata.status' (the "
                "text to display)"
            )
        return self
