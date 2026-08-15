"""The `deckifyr` command-line interface (spec section 11.1).

Every subcommand from the spec is wired up with real argument parsing.
`init`, `validate`, `build`, and `schema` do real work today: `init`
copies the bundled minimal example, `validate` loads and
pydantic-validates a project (design + layouts + presentation,
cross-checking layout references and box unit strings), `build` plans
(`deckifyr.plan`) and composes (`deckifyr.pptx`) a `.pptx` and manifest
for `text`/`markdown`/`image`/`shape`/`group`/`table`/`reportifyr`/
`quarto` elements, and `schema` dumps a document type's JSON Schema.
`preview`, `inspect`, and `serve` parse their arguments fully but raise
`NotImplementedFeatureError` -- the preview renderer, inspector, and web
server are Phase 3/4 work (see deckifyr-specification.md) and
deliberately do not pretend to succeed.

`get`/`set` and the `slide` subcommand group (issue #10) round-trip a
design/layouts/presentation YAML file through `deckifyr.editor`'s pure
dict-manipulation helpers: this module owns reading the file, validating
the edited result against the right `deckifyr.schema` model *before*
writing it back (so a bad edit never corrupts the file on disk), and
turning `deckifyr.editor`'s plain exceptions into `DeckifyrError`s with a
stable code -- `deckifyr.editor`'s own module docstring has the fuller
design writeup. These are real, tested, not stubs.

Exit codes are stable and independent of message wording, per spec
section 11.1:
    0  success
    1  schema/validation failure
    2  argparse usage error (argparse's own default)
    3  I/O failure (missing file, unwritable target, ...)
    4  feature not implemented yet

No subcommand makes network calls (spec section 11.1: "No implicit
network access during a build unless explicitly enabled").
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from deckifyr import editor
from deckifyr.plan import expand_presentation
from deckifyr.pptx import compose_and_write
from deckifyr.schema.colors import resolve_color_tokens
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode, NotImplementedFeatureError
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.units import UnitParseError, parse_length

EXIT_OK = 0
EXIT_VALIDATION_ERROR = 1
EXIT_IO_ERROR = 3
EXIT_NOT_IMPLEMENTED = 4

_EXIT_CODE_BY_ERROR_CODE = {
    ErrorCode.IO: EXIT_IO_ERROR,
    ErrorCode.NOT_IMPLEMENTED: EXIT_NOT_IMPLEMENTED,
}


def _examples_dir() -> Path:
    # inst/python/deckifyr/cli.py -> inst/examples
    return Path(__file__).resolve().parents[2] / "examples" / "minimal-deck"


def _format_pydantic_error(exc: PydanticValidationError, source: str) -> str:
    lines = [f"{source}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)


def _iter_boxes(layouts: LayoutsDocument, presentation: PresentationDocument):
    for layout in layouts.layouts.values():
        for element in layout.elements.values():
            if element.box is not None:
                yield element.box
    for slide in presentation.slides:
        elements = (
            slide.elements.values()
            if isinstance(slide.elements, dict)
            else slide.elements
        )
        for element in elements:
            if element.box is not None:
                yield element.box


def _check_boxes(
    layouts: LayoutsDocument, presentation: PresentationDocument, *, strict: bool
) -> list[str]:
    problems: list[str] = []
    for box in _iter_boxes(layouts, presentation):
        for field_name in ("x", "y", "width", "height"):
            raw = getattr(box, field_name)
            try:
                parse_length(raw, strict=strict)
            except UnitParseError as exc:
                problems.append(f"{field_name}={raw!r}: {exc}")
    return problems


def _load_project(
    presentation_path: Path, *, strict: bool
) -> tuple[PresentationDocument, DesignDocument, LayoutsDocument]:
    """Load and validate design.yaml + layouts.yaml + presentation.yaml.

    This is schema validation and cross-reference checking only (spec
    section 13's "Schema validation" and part of "Static geometry
    validation") -- it does not merge layouts onto slides, resolve
    content, or expand a build plan (spec section 6's pass 1/2), since
    none of that machinery exists yet.
    """
    if not presentation_path.is_file():
        raise DeckifyrError(
            f"presentation file not found: {presentation_path}", code=ErrorCode.IO
        )

    try:
        presentation_data = yaml.safe_load(presentation_path.read_text())
        presentation = PresentationDocument.model_validate(presentation_data)
    except PydanticValidationError as exc:
        raise DeckifyrError(
            _format_pydantic_error(exc, str(presentation_path)),
            code=ErrorCode.SCHEMA_VALIDATION,
        ) from exc

    base_dir = presentation_path.parent
    design_path = base_dir / presentation.design.base
    layouts_path = base_dir / presentation.layouts

    if not design_path.is_file():
        raise DeckifyrError(f"design file not found: {design_path}", code=ErrorCode.IO)
    if not layouts_path.is_file():
        raise DeckifyrError(
            f"layouts file not found: {layouts_path}", code=ErrorCode.IO
        )

    try:
        design = DesignDocument.model_validate(yaml.safe_load(design_path.read_text()))
    except PydanticValidationError as exc:
        raise DeckifyrError(
            _format_pydantic_error(exc, str(design_path)),
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
    # since it also calls `_load_project`.
    design = design.model_copy(
        update={"colors": resolve_color_tokens(design.colors)}
    )

    try:
        layouts = LayoutsDocument.model_validate(
            yaml.safe_load(layouts_path.read_text())
        )
    except PydanticValidationError as exc:
        raise DeckifyrError(
            _format_pydantic_error(exc, str(layouts_path)),
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


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise DeckifyrError(f"file not found: {path}", code=ErrorCode.IO)
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise DeckifyrError(f"{path}: invalid YAML: {exc}", code=ErrorCode.IO) from exc


def _write_yaml(path: Path, data: Any) -> None:
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


def _parse_json_arg(text: str, flag: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeckifyrError(f"{flag}: invalid JSON: {exc}", code=ErrorCode.IO) from exc


def _load_presentation_raw(path: Path) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict) or "slides" not in data:
        raise DeckifyrError(
            f"{path} does not look like a presentation.yaml (no top-level 'slides' key)",
            code=ErrorCode.SCHEMA_VALIDATION,
        )
    return data


def _validate_and_write_presentation(path: Path, data: dict) -> dict[str, Any]:
    """Shared tail of every `slide` mutation and a `set` targeting a
    presentation.yaml: validate the edited dict against
    `PresentationDocument`, best-effort cross-check any `slide.layout`
    against a readable sibling `layouts.yaml` (mirroring `_load_project`'s
    own check, so an edit can't silently introduce a dangling layout
    reference), and only then write -- never on a document that would
    fail its own schema.
    """
    try:
        presentation = PresentationDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise DeckifyrError(
            _format_pydantic_error(exc, str(path)), code=ErrorCode.SCHEMA_VALIDATION
        ) from exc

    layouts_path = path.parent / presentation.layouts
    if layouts_path.is_file():
        try:
            layouts = LayoutsDocument.model_validate(
                yaml.safe_load(layouts_path.read_text())
            )
        except (PydanticValidationError, yaml.YAMLError):
            layouts = None
        if layouts is not None:
            for slide in presentation.slides:
                if slide.layout is not None and slide.layout not in layouts.layouts:
                    raise DeckifyrError(
                        f"slide {slide.id!r} references unknown layout {slide.layout!r}",
                        code=ErrorCode.REFERENCE_NOT_FOUND,
                    )

    _write_yaml(path, data)
    return {"presentation": str(path), "slide_count": len(presentation.slides)}


def _cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.directory)
    target.mkdir(parents=True, exist_ok=True)
    existing = list(target.iterdir())
    if existing and not args.force:
        raise DeckifyrError(
            f"{target} is not empty (use --force to overwrite)", code=ErrorCode.IO
        )

    created = []
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        source = _examples_dir() / name
        destination = target / name
        shutil.copyfile(source, destination)
        created.append(str(destination))

    return {"directory": str(target), "created": created}


def _cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    presentation, design, layouts = _load_project(
        Path(args.presentation), strict=args.strict
    )
    return {
        "valid": True,
        "presentation": str(args.presentation),
        "slide_count": len(presentation.slides),
        "layout_count": len(layouts.layouts),
        "schema_version": presentation.deckifyr,
    }


def _cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    presentation_path = Path(args.presentation).resolve()
    # Fail on schema/geometry problems before planning/composing, so
    # `build` on a broken project reports the real validation error
    # rather than a confusing failure downstream.
    presentation, design, layouts = _load_project(
        Path(args.presentation), strict=args.strict
    )

    project_root = presentation_path.parent
    resolved_slides = expand_presentation(
        presentation, design, layouts, strict=args.strict
    )
    result = compose_and_write(
        presentation,
        design,
        resolved_slides,
        project_root=project_root,
        presentation_path=presentation_path,
        design_path=(project_root / presentation.design.base).resolve(),
        layouts_path=(project_root / presentation.layouts).resolve(),
    )

    return {
        "output": str(result.output_path),
        "manifest": str(result.manifest_path) if result.manifest_path else None,
        "slide_count": result.slide_count,
        "warning_count": len(result.warnings),
    }


_DOCUMENT_MODELS = {
    "design": DesignDocument,
    "layouts": LayoutsDocument,
    "presentation": PresentationDocument,
}


def _resolve_document_type(args_type: str, data: Any) -> str:
    if args_type != "auto":
        return args_type
    try:
        return editor.detect_document_type(data)
    except ValueError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.SCHEMA_VALIDATION) from exc


def _cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.file)
    data = _read_yaml(path)
    try:
        value = editor.get_value(data, args.path)
    except editor.PathError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.PATH_NOT_FOUND) from exc
    return {"file": str(path), "path": args.path, "value": value}


def _parse_set_value(raw: str) -> Any:
    # JSON, not YAML: a YAML scalar parser would treat a bare hex color
    # ("#123456", extremely common in design.yaml) as a comment opener
    # and silently parse it as `None` -- confirmed the hard way while
    # smoke-testing this command by hand. JSON has no comment syntax at
    # all, so `json.loads` either parses `raw` unambiguously as a
    # number/bool/null/array/object (matching --elements-json's own
    # vocabulary) or raises -- at which point `raw` was never valid JSON
    # to begin with, so it's used as a literal string. This means an
    # ordinary bare word/hex color/font name needs no quoting on the
    # command line, while `'"12pt"'`/`true`/`[1, 2]` still work when a
    # caller actually wants a typed value.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _cmd_set(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.file)
    data = _read_yaml(path)

    value: Any = args.value if args.string else _parse_set_value(args.value)

    try:
        editor.set_value(data, args.path, value)
    except editor.PathError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.PATH_NOT_FOUND) from exc

    doc_type = _resolve_document_type(args.type, data)
    if doc_type == "presentation":
        extra = _validate_and_write_presentation(path, data)
    else:
        model = _DOCUMENT_MODELS[doc_type]
        try:
            model.model_validate(data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                _format_pydantic_error(exc, str(path)), code=ErrorCode.SCHEMA_VALIDATION
            ) from exc
        _write_yaml(path, data)
        extra = {}

    return {"file": str(path), "path": args.path, "type": doc_type, **extra}


def _cmd_slide_list(args: argparse.Namespace) -> dict[str, Any]:
    data = _load_presentation_raw(Path(args.presentation))
    return {"presentation": args.presentation, "slides": editor.list_slides(data)}


def _cmd_slide_add(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = _load_presentation_raw(path)
    elements = (
        _parse_json_arg(args.elements_json, "--elements-json")
        if args.elements_json is not None
        else None
    )
    try:
        editor.add_slide(
            data,
            id=args.id,
            layout=args.layout,
            elements=elements,
            notes=args.notes,
            index=args.index,
            after=args.after,
            before=args.before,
        )
    except editor.DuplicateSlideIdError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    except editor.AmbiguousPlacementError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
    return _validate_and_write_presentation(path, data)


def _cmd_slide_remove(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = _load_presentation_raw(path)
    try:
        editor.remove_slide(data, args.id)
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    return _validate_and_write_presentation(path, data)


def _cmd_slide_update(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = _load_presentation_raw(path)

    kwargs: dict[str, Any] = {}
    if args.no_layout:
        kwargs["layout"] = None
    elif args.layout is not None:
        kwargs["layout"] = args.layout
    if args.clear_notes:
        kwargs["notes"] = None
    elif args.notes is not None:
        kwargs["notes"] = args.notes
    if args.elements_json is not None:
        kwargs["elements"] = _parse_json_arg(args.elements_json, "--elements-json")

    try:
        editor.update_slide(data, args.id, **kwargs)
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    return _validate_and_write_presentation(path, data)


def _cmd_slide_move(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = _load_presentation_raw(path)
    try:
        editor.move_slide(
            data, args.id, index=args.index, after=args.after, before=args.before
        )
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    except editor.AmbiguousPlacementError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
    return _validate_and_write_presentation(path, data)


def _cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    raise NotImplementedFeatureError(
        "slide preview rendering is not implemented yet -- see "
        "deckifyr-specification.md section 18, Phase 3"
    )


def _cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    raise NotImplementedFeatureError(
        "inspecting a presentation or .pptx is not implemented yet -- see "
        "deckifyr-specification.md section 18, Phase 1/4"
    )


def _cmd_serve(args: argparse.Namespace) -> dict[str, Any]:
    raise NotImplementedFeatureError(
        "the local web application is not implemented yet -- see "
        "deckifyr-specification.md section 12, Phase 3"
    )


_SCHEMA_MODELS = {
    "design": DesignDocument,
    "layouts": LayoutsDocument,
    "presentation": PresentationDocument,
}


def _cmd_schema(args: argparse.Namespace) -> dict[str, Any]:
    model = _SCHEMA_MODELS[args.document]
    return model.model_json_schema()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deckifyr")
    parser.add_argument(
        "--json", action="store_true", help="emit structured JSON output"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="scaffold a new project from the bundled minimal example"
    )
    init_parser.add_argument("directory", nargs="?", default=".")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=_cmd_init)

    def add_strict_flag(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument(
            "--strict", dest="strict", action="store_true", default=True
        )
        group.add_argument("--warn-only", dest="strict", action="store_false")

    validate_parser = subparsers.add_parser(
        "validate", help="validate a presentation.yaml and its referenced files"
    )
    validate_parser.add_argument("presentation")
    add_strict_flag(validate_parser)
    validate_parser.set_defaults(handler=_cmd_validate)

    build_parser = subparsers.add_parser("build", help="build a .pptx and manifest")
    build_parser.add_argument("presentation")
    add_strict_flag(build_parser)
    build_parser.set_defaults(handler=_cmd_build)

    preview_parser = subparsers.add_parser(
        "preview", help="render slide previews (not implemented yet)"
    )
    preview_parser.add_argument("presentation")
    preview_parser.set_defaults(handler=_cmd_preview)

    inspect_parser = subparsers.add_parser(
        "inspect", help="inspect a presentation or .pptx (not implemented yet)"
    )
    inspect_parser.add_argument("target")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    schema_parser = subparsers.add_parser("schema", help="print a document type's JSON Schema")
    schema_parser.add_argument("document", choices=sorted(_SCHEMA_MODELS))
    schema_parser.set_defaults(handler=_cmd_schema)

    get_parser = subparsers.add_parser(
        "get", help="read a config value from a design/layouts/presentation YAML file"
    )
    get_parser.add_argument("file")
    get_parser.add_argument(
        "path", help="dotted path, e.g. colors.primary or slides[0].notes"
    )
    get_parser.set_defaults(handler=_cmd_get)

    set_parser = subparsers.add_parser(
        "set", help="write a config value into a design/layouts/presentation YAML file"
    )
    set_parser.add_argument("file")
    set_parser.add_argument("path")
    set_parser.add_argument("value")
    set_parser.add_argument(
        "--string",
        action="store_true",
        help=(
            "treat value as a literal string, never as JSON -- needed only for a "
            "value that would otherwise parse as a number/bool/null/array/object "
            "(e.g. the literal text 'true' or 'null')"
        ),
    )
    set_parser.add_argument(
        "--type",
        choices=["auto", "design", "layouts", "presentation"],
        default="auto",
        help="which schema to validate the edited document against (default: auto-detect)",
    )
    set_parser.set_defaults(handler=_cmd_set)

    def add_placement_flags(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument("--index", type=int, default=None, help="0-based position")
        group.add_argument("--after", default=None, help="place immediately after this slide id")
        group.add_argument("--before", default=None, help="place immediately before this slide id")

    slide_parser = subparsers.add_parser(
        "slide", help="add, remove, update, move, or list presentation.yaml's slides"
    )
    slide_subparsers = slide_parser.add_subparsers(dest="slide_command", required=True)

    slide_list_parser = slide_subparsers.add_parser("list", help="list slides in order")
    slide_list_parser.add_argument("presentation")
    slide_list_parser.set_defaults(handler=_cmd_slide_list)

    slide_add_parser = slide_subparsers.add_parser("add", help="add a new slide")
    slide_add_parser.add_argument("presentation")
    slide_add_parser.add_argument("--id", required=True, help="the new slide's unique id")
    slide_add_parser.add_argument(
        "--layout", default=None, help="layout name (omit for a freeform 'layout: null' slide)"
    )
    slide_add_parser.add_argument("--notes", default=None, help="speaker notes text")
    slide_add_parser.add_argument(
        "--elements-json",
        default=None,
        help="JSON object/array to use as the slide's 'elements' block",
    )
    add_placement_flags(slide_add_parser)
    slide_add_parser.set_defaults(handler=_cmd_slide_add)

    slide_remove_parser = slide_subparsers.add_parser("remove", help="remove a slide by id")
    slide_remove_parser.add_argument("presentation")
    slide_remove_parser.add_argument("id")
    slide_remove_parser.set_defaults(handler=_cmd_slide_remove)

    slide_update_parser = slide_subparsers.add_parser(
        "update", help="update an existing slide's layout, notes, or elements"
    )
    slide_update_parser.add_argument("presentation")
    slide_update_parser.add_argument("id")
    layout_group = slide_update_parser.add_mutually_exclusive_group()
    layout_group.add_argument("--layout", default=None, help="new layout name")
    layout_group.add_argument(
        "--no-layout", action="store_true", help="clear the layout (freeform 'layout: null')"
    )
    notes_group = slide_update_parser.add_mutually_exclusive_group()
    notes_group.add_argument("--notes", default=None, help="new speaker notes text")
    notes_group.add_argument("--clear-notes", action="store_true", help="remove speaker notes")
    slide_update_parser.add_argument(
        "--elements-json",
        default=None,
        help="JSON object/array to replace the slide's 'elements' block",
    )
    slide_update_parser.set_defaults(handler=_cmd_slide_update)

    slide_move_parser = slide_subparsers.add_parser("move", help="reorder a slide")
    slide_move_parser.add_argument("presentation")
    slide_move_parser.add_argument("id")
    add_placement_flags(slide_move_parser)
    slide_move_parser.set_defaults(handler=_cmd_slide_move)

    serve_parser = subparsers.add_parser(
        "serve", help="run the local web application (not implemented yet)"
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(handler=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = args.handler(args)
    except DeckifyrError as exc:
        exit_code = _EXIT_CODE_BY_ERROR_CODE.get(exc.code, EXIT_VALIDATION_ERROR)
        if args.json:
            # Deliberately stderr, not stdout, on the error path: the R
            # facade invokes this CLI through pyro::run_python_script(),
            # which uses processx::run(error_on_status = TRUE) and
            # discards the captured stdout/stderr return value whenever
            # the process exits non-zero, replacing it with a generic
            # "<script> failed." error. R/run-python.R works around this
            # by passing its own stderr_callback to capture output as it
            # streams (before the exit-status check fires), which only
            # works if the diagnostic actually went to stderr. Keeping
            # errors on stderr and success on stdout is also just the
            # more conventional CLI split. See R/run-python.R for the R
            # side of this handshake -- the two must not drift apart.
            print(json.dumps({"status": "error", **exc.to_dict()}, indent=2), file=sys.stderr)
        else:
            print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return exit_code

    if args.json:
        print(json.dumps({"status": "ok", **result}, indent=2))
    elif args.command == "schema":
        # A JSON Schema has no nicer "human-readable" form than its own
        # JSON, so print it as-is regardless of --json.
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
