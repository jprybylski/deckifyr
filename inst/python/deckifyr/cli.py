"""The `deckifyr` command-line interface (spec section 11.1).

Every subcommand from the spec is wired up with real argument parsing.
`init`, `validate`, `build`, `preview`, `inspect`, and `schema` do real
work today: `init` copies the bundled minimal example by default, or
scaffolds from `--from-dir PATH`/`--from-repo SPEC` instead (issue #34,
`deckifyr.templates`) -- a local directory or a git repo (`git` must be
on PATH; `SPEC` is `[host/]owner/repo[/subdir][@ref]` shorthand,
defaulting to github.com, or a full URL) either duplicated as a "flat"
source (its own `design.base`/`layouts` files copied under their
original names, with a fresh minimal `presentation.yaml` generated) or,
when it has a `templates/` subdirectory, a "typed" source selected via
`--type NAME` (that type's `presentation.yaml` copied verbatim, as a
real starter). `validate` loads
and pydantic-validates a project (design + layouts + presentation,
cross-checking layout references and box unit strings), `build` plans
(`deckifyr.plan`) and composes (`deckifyr.pptx`) a `.pptx` and manifest
for `text`/`markdown`/`image`/`shape`/`group`/`table`/`reportifyr`/
`quarto` elements, `preview` builds the same way and then rasterizes
each slide to a PNG via `deckifyr.renderers.preview` (LibreOffice +
PyMuPDF -- requires `soffice` on PATH), `inspect` reports a
presentation.yaml's resolved plan or a built .pptx's real slide/shape
structure (detected by file extension), `schema` dumps a document
type's JSON Schema, and `serve` runs the local web application
(`deckifyr.web.app.create_app`, spec section 12) against `--project`
(default: cwd)/`--presentation` (default: `presentation.yaml`),
blocking until interrupted -- it requires the `web` extra
(`deckifyr[web]`) and raises a plain `DeckifyrError` (exit code 3) with
install guidance if `fastapi`/`uvicorn` aren't importable, the same
"tell the caller what to install, don't crash on ImportError" posture
`deckifyr.renderers.preview`/`deckifyr.renderers.quarto` already take
for their own external dependencies. `skills` (issue #50) exports the
package's own bundled coding-agent skill files (Claude Skills-format
`SKILL.md`s under `deckifyr/skills/`, one for `design.yaml`/
`layouts.yaml` authoring and one for `presentation.yaml` authoring) into
`--directory <target>/<skill-name>/SKILL.md` (default: cwd) -- it never
assumes a `.claude/skills/` layout; the caller picks the target
directory, same `directory` positional + `--force` shape as `init`.

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
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from deckifyr import editor, projectio, templates
from deckifyr.diagnostics import warnings_payload
from deckifyr.offline import offline_from_repo_message, offline_mode
from deckifyr.plan import expand_presentation
from deckifyr.policy import (
    ALLOW_OUTSIDE_PROJECT_ENV,
    BINARY_KINDS,
    TRUSTED_BINARIES_ONLY_ENV,
    TrustPolicy,
    resolve_policy,
)
from deckifyr.pptx import BuildResult, compose_and_write
from deckifyr.pptx.compose import sha256_file
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.results import RESULT_VERSION
from deckifyr.textio import read_project_text

EXIT_OK = 0
EXIT_VALIDATION_ERROR = 1
EXIT_IO_ERROR = 3
EXIT_NOT_IMPLEMENTED = 4

_EXIT_CODE_BY_ERROR_CODE = {
    ErrorCode.IO: EXIT_IO_ERROR,
    ErrorCode.NOT_IMPLEMENTED: EXIT_NOT_IMPLEMENTED,
}


def _policy(args: argparse.Namespace) -> TrustPolicy:
    """The launcher's trust policy (issue #89): flag, else environment, else
    off. Subcommands without trust flags (the edit commands) get it from the
    environment alone, which is how a supervising launcher reaches them."""
    return resolve_policy(args, os.environ)


def _examples_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (
        # An installed wheel: setup.py copies the shared example in at build
        # time (issue #86).
        here / "_examples" / "minimal-deck",
        # A repo checkout / editable install / the R package:
        # inst/python/deckifyr/cli.py -> inst/examples.
        here.parents[1] / "examples" / "minimal-deck",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise DeckifyrError(
        "the bundled minimal example project was not found "
        f"(looked in {', '.join(str(c) for c in candidates)}) -- use "
        "`deckifyr init --from-dir`/`--from-repo` instead",
        code=ErrorCode.IO,
    )


def _cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    # Template-based init (issue #34): --from-dir/--from-repo scaffold
    # from a local directory or a git repo instead of the bundled
    # minimal example -- deckifyr.templates owns the actual mechanism,
    # this handler only validates flag combinations and dispatches.
    if args.type is not None and not (args.from_dir or args.from_repo):
        raise DeckifyrError(
            "--type requires --from-dir or --from-repo", code=ErrorCode.IO
        )
    if (args.ref is not None or args.subdir is not None) and not args.from_repo:
        raise DeckifyrError(
            "--ref/--subdir require --from-repo", code=ErrorCode.IO
        )
    if args.from_dir and args.from_repo:
        raise DeckifyrError(
            "--from-dir and --from-repo are mutually exclusive", code=ErrorCode.IO
        )

    if args.from_repo and offline_mode():
        raise DeckifyrError(
            offline_from_repo_message(args.from_repo), code=ErrorCode.IO
        )

    target = Path(args.directory)
    if args.from_dir or args.from_repo:
        return templates.init_from_template(
            target,
            from_dir=args.from_dir,
            from_repo=args.from_repo,
            ref=args.ref,
            subdir=args.subdir,
            type_name=args.type,
            force=args.force,
        )

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


# Bundled Claude Skills-format (SKILL.md) content (issue #50), one
# directory per skill under inst/python/deckifyr/skills/ -- shipped as
# package data (pyproject.toml's package-data), the same "bundled inside
# the package" precedent inst/python/deckifyr/schemas/*.schema.json
# already established for issue #49.
_SKILL_NAMES = ("deckifyr-org-config", "deckifyr-presentation")


def _skills_dir() -> Path:
    return Path(__file__).resolve().parent / "skills"


def _cmd_skills(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.directory)

    # Only refuse on the exact destination files, not the whole target
    # directory's non-emptiness (unlike _cmd_init) -- the target may be
    # e.g. `.claude/skills`, which can legitimately already hold other,
    # unrelated skills.
    conflicts = [
        str(target / name / "SKILL.md")
        for name in _SKILL_NAMES
        if (target / name / "SKILL.md").exists()
    ]
    if conflicts and not args.force:
        raise DeckifyrError(
            f"{', '.join(conflicts)} already exist (use --force to overwrite)",
            code=ErrorCode.IO,
        )

    created = []
    for name in _SKILL_NAMES:
        source = _skills_dir() / name / "SKILL.md"
        destination = target / name / "SKILL.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        created.append(str(destination))

    return {"directory": str(target), "created": created}


def _cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    presentation, design, layouts = projectio.load_project(
        Path(args.presentation), strict=args.strict, policy=_policy(args)
    )
    # Only a `--warn-only` run can have anything to warn about: strict mode
    # already rejected every unitless length inside `load_project`.
    warnings = [] if args.strict else projectio.collect_geometry_warnings(layouts, presentation)
    return {
        "valid": True,
        "presentation": str(args.presentation),
        "slide_count": len(presentation.slides),
        "layout_count": len(layouts.layouts),
        "schema_version": presentation.deckifyr,
        "warnings": warnings_payload(warnings),
    }


def _artifact_entries(result: BuildResult) -> list[dict[str, str]]:
    """`artifacts` for a `--json` result (issue #85): each produced file with
    its SHA-256, so a caller can record provenance without re-hashing."""
    files: list[tuple[str, Path]] = [("pptx", result.output_path)]
    if result.manifest_path:
        files.append(("manifest", result.manifest_path))
    files.extend(("preview", p) for p in result.preview_paths)
    if result.preview_pdf_path:
        files.append(("preview_pdf", result.preview_pdf_path))
    return [{"kind": kind, "path": str(p), "sha256": sha256_file(p)} for kind, p in files]


def _cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    presentation_path = Path(args.presentation).resolve()
    # Fail on schema/geometry problems before planning/composing, so
    # `build` on a broken project reports the real validation error
    # rather than a confusing failure downstream.
    policy = _policy(args)
    presentation, design, layouts = projectio.load_project(
        Path(args.presentation), strict=args.strict, policy=policy
    )

    project_root = presentation_path.parent
    # `--warn-only` coerces unitless lengths to EMUs; report each one
    # (issue #91) -- strict mode already failed above, so nothing to add.
    geometry_warnings = (
        [] if args.strict else projectio.collect_geometry_warnings(layouts, presentation)
    )
    resolved_slides = expand_presentation(
        presentation, design, layouts, strict=args.strict
    )
    # `keep_preview_pdf=True`: harmless when `build.previews` is off (no
    # preview render happens at all, so `result.preview_pdf_path` stays
    # `None`), and when a preview render does happen this build is already
    # paying LibreOffice's PDF-conversion cost to make the PNGs -- keeping
    # that intermediate PDF alongside the built `.pptx` (issue #32) is
    # free, the same reasoning `_cmd_preview` below already uses for its
    # own `keep_preview_pdf=True`.
    result = compose_and_write(
        presentation,
        design,
        resolved_slides,
        project_root=project_root,
        presentation_path=presentation_path,
        design_path=(project_root / presentation.design.base).resolve(),
        layouts_path=(project_root / presentation.layouts).resolve(),
        keep_preview_pdf=True,
        initial_warnings=geometry_warnings,
        policy=policy,
    )

    return {
        "output": str(result.output_path),
        "manifest": str(result.manifest_path) if result.manifest_path else None,
        "slide_count": result.slide_count,
        "warning_count": len(result.warnings),
        # The full list (issue #85) -- previously only the count, with the
        # text reachable only through the optional manifest.
        "warnings": warnings_payload(result.warnings),
        "previews": [str(p) for p in result.preview_paths],
        "preview_pdf": str(result.preview_pdf_path) if result.preview_pdf_path else None,
        "artifacts": _artifact_entries(result),
    }


def _cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.file)
    data = projectio.read_yaml(path)
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
    data = projectio.read_yaml(path)

    value: Any = args.value if args.string else _parse_set_value(args.value)

    try:
        editor.set_value(data, args.path, value)
    except editor.PathError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.PATH_NOT_FOUND) from exc

    doc_type = projectio.resolve_document_type(args.type, data)
    if doc_type == "presentation":
        extra = projectio.validate_and_write_presentation(path, data, policy=_policy(args))
    else:
        model = projectio.DOCUMENT_MODELS[doc_type]
        try:
            model.model_validate(data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        projectio.write_yaml(path, data)
        extra = {}

    return {"file": str(path), "path": args.path, "type": doc_type, **extra}


def _cmd_slide_list(args: argparse.Namespace) -> dict[str, Any]:
    data = projectio.load_presentation_raw(Path(args.presentation))
    return {"presentation": args.presentation, "slides": editor.list_slides(data)}


def _cmd_slide_add(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = projectio.load_presentation_raw(path)
    elements = (
        projectio.parse_json_arg(args.elements_json, "--elements-json")
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
    return projectio.validate_and_write_presentation(path, data, policy=_policy(args))


def _cmd_slide_remove(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = projectio.load_presentation_raw(path)
    try:
        editor.remove_slide(data, args.id)
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    return projectio.validate_and_write_presentation(path, data, policy=_policy(args))


def _cmd_slide_update(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = projectio.load_presentation_raw(path)

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
        kwargs["elements"] = projectio.parse_json_arg(args.elements_json, "--elements-json")

    try:
        editor.update_slide(data, args.id, **kwargs)
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    return projectio.validate_and_write_presentation(path, data, policy=_policy(args))


def _cmd_slide_move(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.presentation)
    data = projectio.load_presentation_raw(path)
    try:
        editor.move_slide(
            data, args.id, index=args.index, after=args.after, before=args.before
        )
    except editor.SlideNotFoundError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
    except editor.AmbiguousPlacementError as exc:
        raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
    return projectio.validate_and_write_presentation(path, data, policy=_policy(args))


def _parse_slides_arg(raw: str | None) -> list[int] | None:
    """Parses `--slides`' comma-separated 1-indexed list (`"1,3"`) into
    `[1, 3]`, or `None` for "not given" (render every slide, unchanged
    from before this flag existed).
    """
    if raw is None:
        return None
    try:
        return [int(token.strip()) for token in raw.split(",") if token.strip()]
    except ValueError as exc:
        raise DeckifyrError(
            f"--slides must be a comma-separated list of integers, got {raw!r}",
            code=ErrorCode.CONTENT_VALIDATION,
        ) from exc


def _cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    presentation_path = Path(args.presentation).resolve()
    policy = _policy(args)
    presentation, design, layouts = projectio.load_project(
        Path(args.presentation), strict=args.strict, policy=policy
    )

    project_root = presentation_path.parent
    resolved_slides = expand_presentation(
        presentation, design, layouts, strict=args.strict
    )
    # `force_previews=True`: an explicit `deckifyr preview` invocation
    # always renders, regardless of the project's own `build.previews`
    # flag -- see `compose_and_write`'s own docstring note on this.
    # `keep_preview_pdf=True`: this command already pays the LibreOffice
    # PDF-conversion cost, so keeping the intermediate PDF around (issue
    # #27's embedded-PDF-viewer support) is free -- `_cmd_build` above
    # does the same (issue #32) whenever `build.previews` actually
    # triggers a render.
    result = compose_and_write(
        presentation,
        design,
        resolved_slides,
        project_root=project_root,
        presentation_path=presentation_path,
        design_path=(project_root / presentation.design.base).resolve(),
        layouts_path=(project_root / presentation.layouts).resolve(),
        force_previews=True,
        preview_slides=_parse_slides_arg(args.slides),
        keep_preview_pdf=True,
        policy=policy,
    )

    return {
        "output": str(result.output_path),
        "previews": [str(p) for p in result.preview_paths],
        "preview_pdf": str(result.preview_pdf_path) if result.preview_pdf_path else None,
        "slide_count": result.slide_count,
        "warning_count": len(result.warnings),
        "warnings": warnings_payload(result.warnings),
        "artifacts": _artifact_entries(result),
    }


def _inspect_presentation(
    path: Path, *, strict: bool, policy: TrustPolicy | None = None
) -> dict[str, Any]:
    presentation, design, layouts = projectio.load_project(path, strict=strict, policy=policy)
    resolved_slides = expand_presentation(presentation, design, layouts, strict=strict)
    return {
        "target": "presentation",
        "path": str(path),
        "schema_version": presentation.deckifyr,
        "slide_count": len(resolved_slides),
        "layout_count": len(layouts.layouts),
        "status_indicator": presentation.status_indicator,
        "slides": [
            {
                "id": slide.id,
                "element_count": len(slide.elements),
                "element_types": sorted({element.type for element in slide.elements}),
                "has_notes": slide.notes is not None,
            }
            for slide in resolved_slides
        ],
    }


def _inspect_pptx(path: Path) -> dict[str, Any]:
    # Imported lazily so `deckifyr inspect some.yaml` never pays for
    # importing python-pptx's own presentation-reading machinery, the
    # same lazy-import posture `deckifyr.resolvers.table` already takes
    # for pyarrow.
    from pptx import Presentation as PptxPresentation

    try:
        prs = PptxPresentation(str(path))
    except Exception as exc:  # python-pptx raises a mix of exception types
        raise DeckifyrError(
            f"{path}: not a readable .pptx package: {exc}", code=ErrorCode.IO
        ) from exc

    slides = []
    for index, slide in enumerate(prs.slides):
        shapes = [
            {
                "name": shape.name,
                "shape_type": str(shape.shape_type),
                "has_text_frame": shape.has_text_frame,
                "rotation": shape.rotation,
            }
            for shape in slide.shapes
        ]
        has_notes = (
            slide.has_notes_slide
            and slide.notes_slide.notes_text_frame.text.strip() != ""
        )
        slides.append(
            {
                "index": index,
                "shape_count": len(shapes),
                "shapes": shapes,
                "has_notes": has_notes,
            }
        )

    manifest_summary = None
    manifest_path = path.with_name(path.stem + ".manifest.json")
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(read_project_text(manifest_path))
        except (OSError, json.JSONDecodeError):
            manifest_data = None
        if isinstance(manifest_data, dict):
            manifest_summary = {
                "path": str(manifest_path),
                "deckifyr_version": manifest_data.get("deckifyr_version"),
                "slide_count": manifest_data.get("slide_count"),
                "warnings": manifest_data.get("warnings", []),
            }

    return {
        "target": "pptx",
        "path": str(path),
        "slide_width_emu": prs.slide_width,
        "slide_height_emu": prs.slide_height,
        "slide_count": len(slides),
        "slides": slides,
        "manifest": manifest_summary,
    }


def _cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.target)
    if not target.is_file():
        raise DeckifyrError(f"target not found: {target}", code=ErrorCode.IO)

    suffix = target.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _inspect_presentation(target, strict=args.strict, policy=_policy(args))
    if suffix == ".pptx":
        return _inspect_pptx(target)
    raise DeckifyrError(
        f"cannot infer target type from extension {suffix!r} -- expected "
        "a presentation .yaml/.yml or a built .pptx",
        code=ErrorCode.IO,
    )


def _cmd_serve(args: argparse.Namespace) -> dict[str, Any]:
    # Imported lazily: the `web` extra (fastapi/uvicorn) is optional, and
    # every other subcommand must keep working without it installed --
    # the same posture `deckifyr.renderers.preview`/`deckifyr.renderers
    # .quarto` already take for their own external dependencies.
    try:
        import uvicorn
    except ImportError as exc:
        if args.launcher == "r":
            how = (
                "re-run `initialize_deck_project()`, which adds fastapi and "
                "uvicorn to the project's deckifyr dependency group (or "
                "install them into the Python environment in use)"
            )
        else:
            how = (
                "run `uv sync --extra web` in a checkout, or install the "
                "release wheel with the [web] extra "
                "(e.g. `uv add \"deckifyr[web] @ <wheel URL>\"`)"
            )
        raise DeckifyrError(
            f"the 'web' extra is not installed -- {how}",
            code=ErrorCode.IO,
        ) from exc

    from deckifyr.web.app import create_app, strip_path_prefix
    from deckifyr.web.security import build_host_policy

    project_root = Path(args.project or ".").resolve()
    server_holder: list[Any] = []

    # Issue #88. The token comes from the environment, never argv (a process
    # listing would show it); a launcher that asked for one and did not set it
    # must fail loudly rather than start an unauthenticated server.
    api_token = None
    if args.api_token_env:
        api_token = os.environ.get(args.api_token_env, "")
        if not api_token:
            raise DeckifyrError(
                f"--api-token-env {args.api_token_env}: that environment variable is "
                "unset or empty, so the server would run without the token it was "
                "asked to require",
                code=ErrorCode.IO,
            )
    # Port 0 means "pick one": the Host header then carries a port we cannot
    # know in advance, so only the names are checked.
    host_policy = build_host_policy(
        args.port or None, args.host, args.allowed_host
    )

    def request_shutdown() -> None:
        # Called from `POST /api/shutdown` once it has decided stopping is
        # safe. uvicorn's own flag: the in-flight response finishes, then the
        # server drains and `Server.run()` returns, so the process exits 0.
        if server_holder:
            server_holder[0].should_exit = True

    app = create_app(
        project_root,
        args.presentation,
        launcher=args.launcher,
        job_timeout_seconds=args.job_timeout,
        request_shutdown=request_shutdown,
        # A supervised/installed context must never shell out to npm at
        # startup; `--launcher workspace` implies this.
        allow_frontend_rebuild=not (args.no_frontend_rebuild or args.launcher == "workspace"),
        policy=_policy(args),
        host_policy=host_policy,
        api_token=api_token,
    )
    served = strip_path_prefix(app, args.root_path) if args.root_path else app
    # Blocks until interrupted (Ctrl-C / SIGINT/SIGTERM) or until
    # `POST /api/shutdown` asks it to stop -- uvicorn's own graceful
    # shutdown either way. `--root-path` (issue #82) is handled by
    # `strip_path_prefix`, not uvicorn's own `root_path` -- see that
    # function's docstring for why.
    server = uvicorn.Server(uvicorn.Config(served, host=args.host, port=args.port))
    server_holder.append(server)
    server.run()
    return {"status": "stopped"}


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
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "include the traceback of an unexpected (non-deckifyr) error in the output "
            "(also enabled by DECKIFYR_DEBUG=1)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="scaffold a new project from the bundled minimal example"
    )
    init_parser.add_argument("directory", nargs="?", default=".")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument(
        "--from-dir",
        default=None,
        metavar="PATH",
        help="use a local directory as the template source instead of the bundled minimal example",
    )
    init_parser.add_argument(
        "--from-repo",
        default=None,
        metavar="SPEC",
        help=(
            "fetch a git repo as the template source: '[host/]owner/repo[/subdir][@ref]' "
            "(host defaults to github.com) or a full URL; requires git on PATH"
        ),
    )
    init_parser.add_argument(
        "--ref",
        default=None,
        help="branch/tag/SHA to check out (only with --from-repo; overrides an embedded @ref)",
    )
    init_parser.add_argument(
        "--subdir",
        default=None,
        help="subdirectory of the resolved repo to use (only with --from-repo; overrides an embedded subdir)",
    )
    init_parser.add_argument(
        "--type",
        default=None,
        metavar="NAME",
        help="template name under a source's templates/<name>/ structure",
    )
    init_parser.set_defaults(handler=_cmd_init)

    skills_parser = subparsers.add_parser(
        "skills",
        help="export bundled coding-agent skill files (SKILL.md) for authoring "
        "design/layouts/presentation YAML",
    )
    skills_parser.add_argument("directory", nargs="?", default=".")
    skills_parser.add_argument("--force", action="store_true")
    skills_parser.set_defaults(handler=_cmd_skills)

    def add_strict_flag(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument(
            "--strict", dest="strict", action="store_true", default=True
        )
        group.add_argument("--warn-only", dest="strict", action="store_false")

    def add_trust_flags(p: argparse.ArgumentParser) -> None:
        """What a supervising launcher uses to stop a project file choosing
        executables or paths (issue #89, `deckifyr.policy`). Every flag also
        has an environment variable, which is how the edit commands (`get`,
        `set`, `slide`) -- which take no flags -- see the same policy."""
        group = p.add_argument_group(
            "trust policy",
            "for launchers that treat project files as untrusted user data; all off by default",
        )
        for kind, (flag, env_name) in BINARY_KINDS.items():
            group.add_argument(
                flag,
                dest=f"{kind}_bin",
                metavar="PATH",
                default=None,
                help=(
                    f"run this executable instead of the project file's own setting "
                    f"(env: {env_name})"
                ),
            )
        group.add_argument(
            "--trusted-binaries-only",
            action="store_true",
            help=(
                "reject a project file whose build.*.binary differs from the default bare "
                "name (E_UNTRUSTED_BINARY) and require design.base, layouts, build.output, "
                "build.manifest and build.reportifyr paths to stay inside the project "
                f"(E_PATH_OUTSIDE_PROJECT) (env: {TRUSTED_BINARIES_ONLY_ENV})"
            ),
        )
        group.add_argument(
            "--allow-outside-project",
            action="store_true",
            help=(
                "with --trusted-binaries-only, permit those paths to resolve outside the "
                f"project (env: {ALLOW_OUTSIDE_PROJECT_ENV})"
            ),
        )

    validate_parser = subparsers.add_parser(
        "validate", help="validate a presentation.yaml and its referenced files"
    )
    validate_parser.add_argument("presentation")
    add_strict_flag(validate_parser)
    add_trust_flags(validate_parser)
    validate_parser.set_defaults(handler=_cmd_validate)

    build_parser = subparsers.add_parser("build", help="build a .pptx and manifest")
    build_parser.add_argument("presentation")
    add_strict_flag(build_parser)
    add_trust_flags(build_parser)
    build_parser.set_defaults(handler=_cmd_build)

    preview_parser = subparsers.add_parser(
        "preview", help="render each slide to a PNG (requires LibreOffice on PATH)"
    )
    preview_parser.add_argument("presentation")
    preview_parser.add_argument(
        "--slides",
        default=None,
        help="comma-separated 1-indexed slide numbers to render (default: all), e.g. 1,3",
    )
    add_strict_flag(preview_parser)
    add_trust_flags(preview_parser)
    preview_parser.set_defaults(handler=_cmd_preview)

    inspect_parser = subparsers.add_parser(
        "inspect", help="inspect a presentation.yaml's resolved plan or a built .pptx"
    )
    inspect_parser.add_argument("target")
    add_strict_flag(inspect_parser)
    add_trust_flags(inspect_parser)
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
        "serve", help="run the local web application (requires the 'web' extra)"
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument(
        "--root-path",
        default="",
        help=(
            "mount prefix (e.g. /apps/deckifyr) for a reverse proxy that does NOT "
            "strip it before forwarding; leave unset behind a prefix-stripping "
            "proxy or when served directly. Either way, browse to the mount URL "
            "with its trailing slash -- the frontend uses page-relative URLs"
        ),
    )
    serve_parser.add_argument(
        "--project", default=None, help="project directory (default: current directory)"
    )
    serve_parser.add_argument(
        "--presentation",
        default="presentation.yaml",
        help="presentation.yaml path, relative to --project (default: presentation.yaml)",
    )
    serve_parser.add_argument(
        "--job-timeout",
        type=float,
        default=600.0,
        help=(
            "seconds a background build/preview job may run before it is killed "
            "(process tree included) and reported as an E_TIMEOUT failure; "
            "0 disables the limit (default: 600)"
        ),
    )
    serve_parser.add_argument(
        "--launcher",
        choices=["cli", "r", "workspace"],
        default="cli",
        help=(
            "who's launching this (default: cli) -- surfaced via GET /api/health "
            "so the frontend's 'no project found' screen can show deckifyr-CLI vs "
            "R-facade vs workspace-launcher guidance; R/serve.R's deck_serve() "
            "passes --launcher r. 'workspace' is for a supervising launcher: it "
            "also implies --no-frontend-rebuild"
        ),
    )
    serve_parser.add_argument(
        "--no-frontend-rebuild",
        action="store_true",
        help=(
            "never run `npm run build` at startup, even in a dev checkout whose "
            "web/src is newer than the committed bundle"
        ),
    )
    serve_parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="HOST[:PORT]",
        help=(
            "also accept this Host/Origin (repeatable) -- the public name of a reverse "
            "proxy in front of the editor. Without a port it matches any port. The "
            "loopback names on the served port and the --host it bound are always allowed; "
            "any other Host gets 421 (DNS-rebinding protection)"
        ),
    )
    serve_parser.add_argument(
        "--api-token-env",
        metavar="VAR",
        default=None,
        help=(
            "name of an environment variable holding a per-launch secret: every /api/* "
            "request except GET /api/health must then send it as X-Deckifyr-Api-Token "
            "(the supervising proxy injects it; the editor's own browser bundle never "
            "sees it). Static assets stay open. The value is read from the environment, "
            "never argv"
        ),
    )
    add_trust_flags(serve_parser)
    serve_parser.set_defaults(handler=_cmd_serve)

    return parser


def _emit_error(args: argparse.Namespace, payload: dict[str, Any], exit_code: int) -> int:
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
        print(
            json.dumps(
                {"status": "error", "result_version": RESULT_VERSION, **payload}, indent=2
            ),
            file=sys.stderr,
        )
    else:
        print(f"ERROR [{payload['code']}]: {payload['message']}", file=sys.stderr)
        if payload["code"] == ErrorCode.INTERNAL and "traceback" not in payload:
            print("(re-run with --debug for the traceback)", file=sys.stderr)
        elif "traceback" in payload:
            print(payload["traceback"], file=sys.stderr)
    return exit_code


def _debug_enabled(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "debug", False)) or os.environ.get("DECKIFYR_DEBUG", "") not in (
        "",
        "0",
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = args.handler(args)
    except DeckifyrError as exc:
        exit_code = _EXIT_CODE_BY_ERROR_CODE.get(exc.code, EXIT_VALIDATION_ERROR)
        return _emit_error(args, exc.to_dict(), exit_code)
    except Exception as exc:
        # Not one of ours (issue #90): without this, a `PermissionError`
        # (say, the output .pptx is open in PowerPoint on Windows) or a
        # genuine bug escapes as a bare traceback with no JSON on stderr,
        # which breaks the `--json` contract callers (the R facade, the
        # web job manager, a launcher) depend on. An OS-level failure is an
        # I/O error; anything else is internal. The traceback is kept out of
        # the default output (it is noise to a caller and may carry paths)
        # and opt-in via `--debug`/DECKIFYR_DEBUG, where it rides inside the
        # one JSON object rather than as extra stderr text that would make
        # the payload unparseable.
        code = ErrorCode.IO if isinstance(exc, OSError) else ErrorCode.INTERNAL
        payload: dict[str, Any] = {
            "code": code,
            "message": f"{type(exc).__name__}: {exc}",
        }
        if _debug_enabled(args):
            payload["traceback"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        return _emit_error(args, payload, _EXIT_CODE_BY_ERROR_CODE.get(code, EXIT_VALIDATION_ERROR))

    if args.json:
        print(json.dumps({"status": "ok", "result_version": RESULT_VERSION, **result}, indent=2))
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
