"""Pydantic models for `presentation.yaml` (spec section 7.6).

Slide order, content references, geometry overrides, notes, and build
settings. This module only validates shape -- it does not resolve
`design.base`/`layouts` paths, merge layouts onto slides, or expand
`{rpfy}:` references; that's the plan-resolution step described in spec
section 6, not yet implemented (see the module docstring in
`deckifyr.resolvers`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from deckifyr.schema.layouts import Element, StatusIndicatorMode
from deckifyr.schema.version import check_schema_version


class DesignRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str


class Metadata(BaseModel):
    # Open-ended: orgs attach arbitrary metadata fields (study id, status,
    # confidentiality, ...) beyond the ones the spec's example shows.
    model_config = ConfigDict(extra="allow")

    title: str
    author: str | None = None
    # Free text ("draft", "demo", "final", ...) -- also the default
    # status-indicator text (spec section 7.8) when `PresentationDocument
    # .watermark` is unset (`deckifyr.plan.expand_presentation`), so a
    # deck doesn't need the same word typed in two places.
    status: str | None = None


class ReportifyrConfig(BaseModel):
    """Where/how to resolve `{rpfy}:` magic strings (spec section 9.1),
    project-relative paths. `standard_footnotes` is required only
    lazily -- a build with no `reportifyr`/rpfy-sourced element never
    reads it; `deckifyr.pptx.compose` raises a `ContentValidationError`
    if one exists and this is unset.
    """

    model_config = ConfigDict(extra="forbid")

    outputs_dir: str = "OUTPUTS"
    standard_footnotes: str | None = None
    # Mirrors reportifyr's own `add_footnotes()` R parameter of the same
    # name and default -- reportifyr has no `config.yaml`-level
    # equivalent (it's a call-time argument there too), so this is
    # deckifyr's own project-level home for the same choice.
    fail_on_missing_metadata: bool = True


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
    binary: str = "quarto"
    timeout_seconds: float = 60
    max_output_bytes: int = 5_000_000


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

    binary: str = "soffice"
    dpi: int = 110
    timeout_seconds: float = 120


class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strict: bool = True
    output: str
    manifest: str | None = None
    # Whether `deckifyr build` also renders a PNG per slide alongside the
    # `.pptx` (spec section 7.6's own example) -- `deckifyr preview`
    # (spec section 11.1) always renders previews regardless of this
    # flag; this only controls whether an ordinary `build` does too.
    previews: bool = False
    reportifyr: ReportifyrConfig | None = None
    quarto: QuartoConfig | None = None
    preview: PreviewConfig | None = None


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    # `layout: null` (no layout at all, spec section 7.6's "freeform"
    # example) is a valid, distinct choice from omitting the field, so
    # this stays a required key that may hold None rather than an
    # optional-with-default field.
    layout: str | None
    # Dict form keys elements by name to override/extend a layout's
    # named slots (spec section 7.7: "Named elements are essential.
    # Array indices should never be the primary override mechanism.");
    # list form is only for freeform slides with `layout: null`, where
    # there is no named layout to key against and each element carries
    # its own `id`.
    elements: dict[str, Element] | list[Element] = {}
    # Speaker notes (spec section 7.1's file-responsibility table, section
    # 18 Phase 1). Plain text, not a slide element -- no box/style/z_index,
    # composed straight onto the slide's native notes page rather than
    # through the ordinary element pipeline.
    notes: str | None = None


class PresentationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deckifyr: str
    design: DesignRef
    layouts: str
    metadata: Metadata
    build: BuildConfig
    # Which of `design.yaml`'s `furniture.status` placements (spec
    # section 7.8) this build uses -- `None` (equivalent to `"none"`,
    # the default) shows no status/watermark mark at all. Selecting a
    # placement `design.yaml` never configured a `StatusIndicatorStyle`
    # for is a build-time `ContentValidationError`
    # (`deckifyr.plan._furniture_layout`), not a silent no-op.
    status_indicator: StatusIndicatorMode | None = None
    # The status/watermark mark's own text -- any word, a build-time
    # choice (spec section 7.8), not a `design.yaml` constant. `None`
    # (the default -- expected the common case) falls back to
    # `metadata.status` (`deckifyr.plan.expand_presentation`), the same
    # free-text field authors already set for descriptive purposes
    # ("draft", "demo", "final", ...), so a status/watermark mark
    # doesn't require typing the same word twice; set this explicitly
    # only when the mark's text should differ from `metadata.status`.
    # Simply unused when `status_indicator` selects nothing (see
    # `_check_status_indicator_has_watermark_text` below for the one
    # case where having neither this nor `metadata.status` is a
    # validation error rather than a quiet no-op).
    watermark: str | None = None
    slides: list[Slide]

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
    def _check_status_indicator_has_watermark_text(self) -> "PresentationDocument":
        # A full-page watermark with no text would be a large, silently
        # empty rotated box -- worth failing the build over, unlike a
        # small corner placement with no text (`deckifyr.plan
        # ._furniture_layout` simply skips that one, the same "no
        # content, not required" rule an empty layout zone already
        # follows). Only `"watermark"` gets this stricter check. `watermark`
        # unset is fine as long as `metadata.status` supplies the text
        # instead (`deckifyr.plan.expand_presentation`'s own fallback) --
        # this only fails when *neither* would give the compositor
        # anything to show.
        if (
            self.status_indicator == "watermark"
            and self.watermark is None
            and self.metadata.status is None
        ):
            raise ValueError(
                "status_indicator: watermark requires either a non-null "
                "'watermark' value or a non-null 'metadata.status' (the "
                "text to display)"
            )
        return self
