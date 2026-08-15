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

from deckifyr.plan import expand_presentation
from deckifyr.pptx import compose_and_write
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
