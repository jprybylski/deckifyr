"""Loading, validating, and writing a project's design/layouts/presentation
YAML documents (spec section 13's "Schema validation" and part of "Static
geometry validation").

This is the same "mechanism in its own module, orchestration in `cli.py`"
split `deckifyr.editor`/`deckifyr.plan` already establish: everything here
operates on a filesystem path and plain, already-parsed YAML data, with no
argparse and no JSON-envelope building of its own. `deckifyr.cli` is today's
only caller, but this module exists as its own thing specifically so a
forthcoming `deckifyr.web` (spec section 12, Phase 3) can load/validate/write
the same project files without importing `deckifyr.cli` for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from deckifyr import editor
from deckifyr.diagnostics import W_UNITLESS_LENGTH, BuildWarning
from deckifyr.policy import PERMISSIVE, TrustPolicy, check_presentation_policy
from deckifyr.schema.colors import resolve_color_tokens
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.units import UnitParseError, is_unitless, parse_length


def format_pydantic_error(exc: PydanticValidationError, source: str) -> str:
    lines = [f"{source}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)


_BOX_FIELDS = ("x", "y", "width", "height")


def _iter_boxes(layouts: LayoutsDocument, presentation: PresentationDocument):
    """Yield `(slide_id, element_id, where, box)` for every declared box.

    `slide_id` is `None` for a layout zone; `where` is a human label
    ("layout 'title' zone 'heading'") used in warnings.
    """
    for layout_id, layout in layouts.layouts.items():
        for zone_id, element in layout.elements.items():
            if element.box is not None:
                yield None, zone_id, f"layout {layout_id!r} zone {zone_id!r}", element.box
    for slide in presentation.slides:
        if isinstance(slide.elements, dict):
            pairs = list(slide.elements.items())
        else:
            pairs = [(element.id, element) for element in slide.elements]
        for element_id, element in pairs:
            if element.box is not None:
                yield (
                    slide.id,
                    element_id,
                    f"slide {slide.id!r} element {element_id!r}",
                    element.box,
                )


def _check_boxes(
    layouts: LayoutsDocument, presentation: PresentationDocument, *, strict: bool
) -> list[str]:
    problems: list[str] = []
    for _slide_id, _element_id, _where, box in _iter_boxes(layouts, presentation):
        for field_name in _BOX_FIELDS:
            raw = getattr(box, field_name)
            try:
                parse_length(raw, strict=strict)
            except UnitParseError as exc:
                problems.append(f"{field_name}={raw!r}: {exc}")
    return problems


def collect_geometry_warnings(
    layouts: LayoutsDocument, presentation: PresentationDocument
) -> list[BuildWarning]:
    """One `W_UNITLESS_LENGTH` warning per unitless box length (issue #91).

    Only meaningful for a non-strict (`--warn-only`) run: strict mode rejects
    these in `load_project`, so there is nothing left to warn about. In
    non-strict mode `parse_length` coerces a bare number to EMUs, which is
    almost never what an author meant by `x: 1` -- surface each one instead
    of accepting it silently.
    """
    warnings: list[BuildWarning] = []
    for slide_id, element_id, where, box in _iter_boxes(layouts, presentation):
        for field_name in _BOX_FIELDS:
            raw = getattr(box, field_name)
            if is_unitless(raw):
                warnings.append(
                    BuildWarning(
                        f"{where}: box {field_name}={raw!r} has no unit and is read as "
                        "EMUs (914400 per inch); write an explicit unit such as '1in'",
                        code=W_UNITLESS_LENGTH,
                        slide=slide_id,
                        element=element_id,
                    )
                )
    return warnings


def load_project(
    presentation_path: Path,
    *,
    strict: bool,
    presentation_data: dict[str, Any] | None = None,
    design_data: dict[str, Any] | None = None,
    layouts_data: dict[str, Any] | None = None,
    policy: TrustPolicy | None = None,
) -> tuple[PresentationDocument, DesignDocument, LayoutsDocument]:
    """Load and validate design.yaml + layouts.yaml + presentation.yaml.

    This is schema validation and cross-reference checking only (spec
    section 13's "Schema validation" and part of "Static geometry
    validation") -- it does not merge layouts onto slides, resolve
    content, or expand a build plan (spec section 6's pass 1/2); that's
    `deckifyr.plan.expand_presentation`.

    `presentation_data`/`design_data`/`layouts_data` are optional raw-dict
    overrides: when given, that document is validated directly instead of
    being re-read from disk (its on-disk `is_file()`/`read_text()` step is
    skipped entirely). This is what lets `deckifyr.web.app` resolve its
    in-memory working copy through this same function -- the sole plan/
    validation engine -- instead of duplicating any of this logic against
    already-parsed dicts.

    `policy` (issue #89, `deckifyr.policy`): what the project file is trusted
    to choose. `None` is the permissive default every pre-existing caller gets.
    It is enforced right after `presentation.yaml` itself validates and
    *before* `design.yaml`/`layouts.yaml` are read, because a `design.base`
    pointing outside the project is exactly the read being prevented.
    """
    if presentation_data is not None:
        try:
            presentation = PresentationDocument.model_validate(presentation_data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                format_pydantic_error(exc, str(presentation_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
    else:
        if not presentation_path.is_file():
            raise DeckifyrError(
                f"presentation file not found: {presentation_path}", code=ErrorCode.IO
            )
        try:
            presentation_data = yaml.safe_load(presentation_path.read_text())
            presentation = PresentationDocument.model_validate(presentation_data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                format_pydantic_error(exc, str(presentation_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc

    base_dir = presentation_path.parent
    check_presentation_policy(presentation, base_dir, policy or PERMISSIVE)
    design_path = base_dir / presentation.design.base
    layouts_path = base_dir / presentation.layouts

    if design_data is None:
        if not design_path.is_file():
            raise DeckifyrError(f"design file not found: {design_path}", code=ErrorCode.IO)
        design_data = yaml.safe_load(design_path.read_text())

    try:
        design = DesignDocument.model_validate(design_data)
    except PydanticValidationError as exc:
        raise DeckifyrError(
            format_pydantic_error(exc, str(design_path)),
            code=ErrorCode.SCHEMA_VALIDATION,
        ) from exc

    # Resolve any `colors:` derivations (issue #11) to literal hex strings
    # here, once, right after `design.yaml` is parsed -- `deckifyr.plan`
    # and `deckifyr.pptx.compose` both read `design.colors` directly off
    # this same object independently of one another, so every existing
    # `design.colors.get(token, token)` call site in both keeps working
    # unchanged only if the derivations are already gone by the time
    # either sees `design`. `ColorResolutionError` (raised only for a
    # circular derivation chain) is already a `DeckifyrError` subclass,
    # so it propagates through this function's normal error path with no
    # extra wrapping -- and `deckifyr validate` gets this check for free
    # since it also calls `load_project`.
    design = design.model_copy(
        update={"colors": resolve_color_tokens(design.colors)}
    )

    if layouts_data is None:
        if not layouts_path.is_file():
            raise DeckifyrError(
                f"layouts file not found: {layouts_path}", code=ErrorCode.IO
            )
        layouts_data = yaml.safe_load(layouts_path.read_text())

    try:
        layouts = LayoutsDocument.model_validate(layouts_data)
    except PydanticValidationError as exc:
        raise DeckifyrError(
            format_pydantic_error(exc, str(layouts_path)),
            code=ErrorCode.SCHEMA_VALIDATION,
        ) from exc

    for slide in presentation.slides:
        if slide.layout is not None and slide.layout not in layouts.layouts:
            raise DeckifyrError(
                f"slide {slide.id!r} references unknown layout {slide.layout!r}",
                code=ErrorCode.REFERENCE_NOT_FOUND,
            )

    box_problems = _check_boxes(layouts, presentation, strict=strict)
    if box_problems:
        raise DeckifyrError(
            "invalid element geometry:\n  " + "\n  ".join(box_problems),
            code=ErrorCode.UNIT_PARSE,
        )

    return presentation, design, layouts


# --- Shared helpers for `get`/`set`/`slide` (issue #10) -----------------


def read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise DeckifyrError(f"file not found: {path}", code=ErrorCode.IO)
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise DeckifyrError(f"{path}: invalid YAML: {exc}", code=ErrorCode.IO) from exc


def write_yaml(path: Path, data: Any) -> None:
    # Written to a sibling temp file and atomically renamed into place
    # (`Path.replace` is `os.replace` under the hood) so a crash
    # mid-write can never leave a half-written config file behind.
    # `sort_keys=False` preserves the mapping key order editor.py's
    # mutations leave dicts in (Python dicts are order-preserving, and
    # PyYAML respects that when told not to re-sort) -- important since
    # these functions edit a document a human wrote and will read again,
    # not just round-trip machine state.
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text)
    tmp_path.replace(path)


def parse_json_arg(text: str, flag: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeckifyrError(f"{flag}: invalid JSON: {exc}", code=ErrorCode.IO) from exc


def load_presentation_raw(path: Path) -> dict[str, Any]:
    data = read_yaml(path)
    if not isinstance(data, dict) or "slides" not in data:
        raise DeckifyrError(
            f"{path} does not look like a presentation.yaml (no top-level 'slides' key)",
            code=ErrorCode.SCHEMA_VALIDATION,
        )
    return data


def validate_presentation_data(
    path: Path,
    data: dict,
    *,
    layouts_data: Any | None = None,
    policy: TrustPolicy | None = None,
) -> PresentationDocument:
    """Validate `data` against `PresentationDocument`, then best-effort
    cross-check any `slide.layout` against `layouts.yaml` (mirroring
    `load_project`'s own check, so an edit can't silently introduce a
    dangling layout reference). Shared by `validate_and_write_presentation`
    (the disk-writing CLI path, no `layouts_data` -- reads the sibling
    file) and `deckifyr.web.app`'s in-memory working-copy mutation path
    (`layouts_data=working_copy.get("layouts")`), which validates the
    same way but against whatever `layouts.yaml` looks like in the
    current unsaved session, not what's on disk -- issue #30's new
    layout add/remove routes are the first thing that can make those two
    diverge within one `deckifyr serve` session (a layout added but not
    yet Saved must already be a valid `slide.layout` target), so a plain
    disk read here would incorrectly reject it. `layouts_data=None`
    (every pre-existing caller) keeps the original disk-read behavior
    exactly.

    `policy` (issue #89) rejects an edit that would introduce an untrusted
    `binary` or an out-of-project path *before* it is accepted -- the editor's
    config PUT and every element/slide mutation reach it through here, so a
    project file cannot be edited into one the launcher would refuse to load.
    """
    try:
        presentation = PresentationDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise DeckifyrError(
            format_pydantic_error(exc, str(path)), code=ErrorCode.SCHEMA_VALIDATION
        ) from exc
    check_presentation_policy(presentation, path.parent, policy or PERMISSIVE)

    if layouts_data is None:
        layouts_path = path.parent / presentation.layouts
        if layouts_path.is_file():
            try:
                layouts_data = yaml.safe_load(layouts_path.read_text())
            except yaml.YAMLError:
                layouts_data = None

    if layouts_data is not None:
        try:
            layouts = LayoutsDocument.model_validate(layouts_data)
        except PydanticValidationError:
            layouts = None
        if layouts is not None:
            for slide in presentation.slides:
                if slide.layout is not None and slide.layout not in layouts.layouts:
                    raise DeckifyrError(
                        f"slide {slide.id!r} references unknown layout {slide.layout!r}",
                        code=ErrorCode.REFERENCE_NOT_FOUND,
                    )

    return presentation


def validate_and_write_presentation(
    path: Path, data: dict, *, policy: TrustPolicy | None = None
) -> dict[str, Any]:
    """Shared tail of every `slide` mutation and a `set` targeting a
    presentation.yaml: validate (`validate_presentation_data`) and only
    then write -- never on a document that would fail its own schema.
    """
    presentation = validate_presentation_data(path, data, policy=policy)
    write_yaml(path, data)
    return {"presentation": str(path), "slide_count": len(presentation.slides)}


DOCUMENT_MODELS = {
    "design": DesignDocument,
    "layouts": LayoutsDocument,
    "presentation": PresentationDocument,
}


def resolve_document_type(args_type: str, data: Any) -> str:
    if args_type != "auto":
        return args_type
    try:
        return editor.detect_document_type(data)
    except ValueError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.SCHEMA_VALIDATION) from exc
