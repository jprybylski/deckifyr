"""Pydantic models for `presentation.yaml` (spec section 7.6).

Slide order, content references, geometry overrides, notes, and build
settings. This module only validates shape -- it does not resolve
`design.base`/`layouts` paths, merge layouts onto slides, or expand
`{rpfy}:` references; that's the plan-resolution step described in spec
section 6, not yet implemented (see the module docstring in
`deckifyr.resolvers`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from deckifyr.schema.layouts import Element
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


class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strict: bool = True
    output: str
    manifest: str | None = None
    previews: bool = False
    reportifyr: ReportifyrConfig | None = None


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
