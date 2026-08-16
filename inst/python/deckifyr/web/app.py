"""The `deckifyr.web` FastAPI backend (spec section 12, Phase 3).

An authoring/build interface over the same engine the CLI already
uses -- `deckifyr.projectio`/`deckifyr.editor`/`deckifyr.plan`, never a
second, web-only presentation engine (this package's own `__init__.py`
docstring). `create_app` binds to one project root and one
`presentation.yaml` for the lifetime of the process (matching
`deckifyr serve`'s own single-project CLI invocation, `cli.py`'s
`_cmd_serve`); every route resolves `design.yaml`/`layouts.yaml`
relative to that bound presentation the same way `projectio.load_project`
already does -- `presentation.design.base`/`presentation.layouts`, not a
second path-resolution scheme.

Handlers return plain `dict[str, Any]`, matching `cli.py`'s own handler
style -- no second, parallel pydantic response-model layer on top of the
schema models `deckifyr.schema` already defines.

`POST /api/build` never composes in-process; it hands off to
`deckifyr.web.jobs.JobManager`, which shells out to a real
`python -m deckifyr --json build ...` subprocess and polls it from a
background thread (see that module's own docstring for why).
"""

from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError

from deckifyr import editor, projectio
from deckifyr.plan import (
    FURNITURE_BACKGROUND_ID,
    FURNITURE_BRANDING_ID,
    FURNITURE_PAGE_NUMBER_ID,
    FURNITURE_STATUS_ID,
    STATUS_INDICATOR_FIELDS,
    ResolvedElement,
    ResolvedSlide,
    expand_presentation,
    expand_slide,
    resolve_watermark_text,
)
from deckifyr.renderers.preview import LIBREOFFICE_INSTALL_URL
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.layouts import Element, LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument, Slide
from deckifyr.schema.units import EMU_PER_INCH, format_length, parse_length
from deckifyr.web.jobs import JobManager

# The synthetic slide id `GET /api/furniture`/the furniture PATCH/POST/
# DELETE routes below use for design.yaml's furniture block (issue #21).
# Not a real `presentation.yaml` slide id -- `_FURNITURE_*_ID` constants
# (element ids within it) already reserve the `__furniture_` prefix
# against author-chosen ids, and this sentinel follows the same
# convention one level up.
FURNITURE_SLIDE_ID = "__furniture__"

# spec section 11.1's own DeckifyrError code -> HTTP status mapping,
# translated to this web layer: an `E_IO` failure ("file not found") is
# a 404, every validation-shaped code is a 422 (the request was
# understood but rejected on content grounds), a missing external
# binary is a 424 (Failed Dependency -- there IS a missing upstream
# dependency, which is exactly what that status code means), and
# anything else (a real bug, not a caller mistake) is a 500.
_ERROR_CODE_STATUS: dict[str, int] = {
    ErrorCode.SCHEMA_VALIDATION: 422,
    ErrorCode.UNIT_PARSE: 422,
    ErrorCode.UNIT_REQUIRED: 422,
    ErrorCode.REFERENCE_NOT_FOUND: 422,
    ErrorCode.CONTENT_VALIDATION: 422,
    ErrorCode.COLOR_RESOLUTION: 422,
    ErrorCode.PATH_NOT_FOUND: 422,
    ErrorCode.IO: 404,
    ErrorCode.MISSING_DEPENDENCY: 424,
}


def _serialize_element(element: ResolvedElement) -> dict[str, Any]:
    """A `ResolvedElement` as plain JSON -- geometry formatted through
    `format_length` (inches) rather than raw EMU ints, so the frontend
    never has to know EMU exists (spec section 7.3 keeps that unit
    entirely internal). `children` is re-serialized recursively rather
    than left to `dataclasses.asdict`'s own recursion, so each child
    gets the same `box` treatment as its parent, not raw `x`/`y`/`width`/
    `height` ints.
    """
    data = asdict(element)
    for key in ("x", "y", "width", "height"):
        data.pop(key, None)
    data["box"] = {
        "x": format_length(element.x),
        "y": format_length(element.y),
        "width": format_length(element.width),
        "height": format_length(element.height),
    }
    data["children"] = [_serialize_element(child) for child in element.children]
    return data


def _serialize_slide(slide: ResolvedSlide) -> dict[str, Any]:
    return {
        "id": slide.id,
        "notes": slide.notes,
        "elements": [_serialize_element(element) for element in slide.elements],
    }


# --- furniture pseudo-slide helpers (issue #21) -----------------------
#
# `GET /api/furniture` reuses `deckifyr.plan.expand_slide` verbatim (see
# that function's own docstring) rather than a second furniture-resolving
# code path -- passing a synthetic, empty `Slide` and `layout=None` makes
# it return exactly `design.yaml`'s furniture elements, resolved the same
# way a real slide's are. The PATCH/POST/DELETE routes below are new,
# though: they write back to `design.yaml`'s raw dict, not
# `presentation.yaml`'s, so they can't reuse `patch_element`'s own
# `prefix`-building logic even though the shape is deliberately similar.


def _resolve_furniture_target(
    element_id: str, presentation_doc: PresentationDocument
) -> tuple[str, bool, bool, str | None]:
    """Map a furniture element id to `(design.yaml dotted path, supports
    rotation, supports z_index, value-edit field name or None)`.

    Raises `DeckifyrError` (`PATH_NOT_FOUND`) for ids with no editable
    geometry at all (`background`, which always fills the slide with no
    `box` of its own in the schema) or whose target isn't selectable
    right now (`status` with no `status_indicator` chosen in
    `presentation.yaml`) -- both are "there's nothing here to edit yet"
    in spirit, the same status a missing `set_value` parent already
    produces via `_set_element_field` below.
    """
    if element_id == FURNITURE_BACKGROUND_ID:
        raise DeckifyrError(
            "the background furniture item has no editable geometry -- "
            "it always fills the slide; set design.yaml's "
            "slide.background_image via the Config tab instead",
            code=ErrorCode.PATH_NOT_FOUND,
        )
    if element_id == FURNITURE_STATUS_ID:
        indicator = presentation_doc.status_indicator
        if indicator is None or indicator == "none":
            raise DeckifyrError(
                "no status indicator is selected -- choose one in "
                "Deck Options first",
                code=ErrorCode.PATH_NOT_FOUND,
            )
        field_name = STATUS_INDICATOR_FIELDS[indicator]
        return f"furniture.status.{field_name}", True, True, None
    if element_id == FURNITURE_BRANDING_ID:
        return "furniture.branding", False, False, "text"
    if element_id == FURNITURE_PAGE_NUMBER_ID:
        return "furniture.page_number", False, False, None
    raise HTTPException(status_code=404, detail=f"unknown furniture element {element_id!r}")


def _slide_size_in(design_data: dict[str, Any]) -> tuple[float, float]:
    slide = design_data.get("slide") or {}
    width = parse_length(slide.get("width", "13.333in"), strict=True)
    height = parse_length(slide.get("height", "7.5in"), strict=True)
    return width / EMU_PER_INCH, height / EMU_PER_INCH


def _default_box(x_in: float, y_in: float, width_in: float, height_in: float) -> dict[str, str]:
    return {
        "x": f"{x_in:.3f}in",
        "y": f"{y_in:.3f}in",
        "width": f"{width_in:.3f}in",
        "height": f"{height_in:.3f}in",
    }


def _resolve_layout_zone(
    element_id: str, element: Element, design_data: dict[str, Any], order: int
) -> dict[str, Any]:
    """A `layouts.yaml` zone as `_serialize_element`-shaped JSON (issue
    #23's Content/Layout tab), deliberately *not* built by reusing
    `deckifyr.plan.expand_slide`/`_resolve_element` the way the furniture
    pseudo-slide (`GET /api/furniture`) reuses it for its own synthetic
    slide.

    A real layout zone typically has no `value`/`source` of its own at
    all -- that's the slide override's job (spec section 7.2/7.6's whole
    override model; `title-content`'s own `content` zone is `type: slot`
    with no value, only ever filled in by a slide) -- and `slot`/
    `footnotes` aren't even in `SUPPORTED_ELEMENT_TYPES`. Confirmed the
    hard way, not assumed: `_resolve_element`'s content-presence gate
    (`_has_content`) means an empty, non-required zone silently resolves
    to `None` (dropped entirely, not shown) and an empty *required* zone
    (e.g. this layout's own `title`) hard-raises `ContentValidationError`
    -- both wrong for a view whose whole point is showing every zone's
    box so it can be dragged, regardless of whether it currently holds
    content. So this resolves geometry/type/chrome directly from the
    `Element` schema object instead, with no content-presence gate and no
    `SUPPORTED_ELEMENT_TYPES`/`required` enforcement -- those remain
    build-time concerns, checked once a slide actually uses this layout
    (`expand_slide`, unchanged).
    """
    box = element.box
    if box is not None:
        box_json = {
            "x": format_length(parse_length(box.x, strict=True)),
            "y": format_length(parse_length(box.y, strict=True)),
            "width": format_length(parse_length(box.width, strict=True)),
            "height": format_length(parse_length(box.height, strict=True)),
        }
    else:
        width_in, height_in = _slide_size_in(design_data)
        box_json = _default_box(0.5, 0.5, min(3.0, width_in * 0.3), 0.4)
    return {
        "id": element_id,
        "type": element.type or "text",
        "value": element.value,
        "source": element.source,
        "box": box_json,
        "rotation": element.rotation or 0,
        "z_index": element.z_index or 0,
        "order": order,
        "style": None,
        "fit": element.fit or "contain",
        "overflow": element.overflow or "error",
        "render_mode": element.render_mode or "native",
        "alt_text": element.alt_text,
        "required": element.required,
        "footer_placement": element.footer_placement,
        "shape_kind": element.shape_kind,
        "shape_style": None,
        "table_style": element.table_style,
        "center": element.center,
        "align": element.align,
        "children": [],
    }


class _WorkingCopy:
    """In-memory copy of design.yaml/layouts.yaml/presentation.yaml for one
    `deckifyr serve` process (issue #24's deferred-save editor). Every
    mutating handler below applies its edit here instead of to the file
    directly; `POST /api/save` is the only place that still calls
    `projectio.write_yaml` for a document actually touched this session.
    Closure-scoped to one `create_app()` call (constructed inside it,
    like `job_manager`), so it's independent per project/process --
    required since `tests/python/test_web.py` creates multiple
    `create_app()` instances in one test process.

    Lazily loads each document's raw dict on first access (mirrors the
    old always-read-from-disk behavior for whichever doc is asked for
    first); `discard()` drops everything so the next access re-reads
    from disk.
    """

    def __init__(self, presentation_path: Path):
        self._presentation_path = presentation_path
        self._docs: dict[str, Any] = {"presentation": None, "design": None, "layouts": None}
        self._dirty: set[str] = set()

    def _design_layouts_paths(self) -> tuple[Path, Path]:
        presentation_data = self.get("presentation") or {}
        base_dir = self._presentation_path.parent
        design_base = (presentation_data.get("design") or {}).get("base", "design.yaml")
        layouts_rel = presentation_data.get("layouts", "layouts.yaml")
        return (base_dir / design_base).resolve(), (base_dir / layouts_rel).resolve()

    def path_for(self, doc: str) -> Path:
        if doc == "presentation":
            return self._presentation_path
        design_path, layouts_path = self._design_layouts_paths()
        return design_path if doc == "design" else layouts_path

    def get(self, doc: str) -> Any:
        if self._docs[doc] is None:
            self._docs[doc] = projectio.read_yaml(self.path_for(doc))
        return self._docs[doc]

    def set(self, doc: str, data: Any) -> None:
        self._docs[doc] = data
        self._dirty.add(doc)

    @property
    def dirty(self) -> bool:
        return bool(self._dirty)

    def save(self) -> list[str]:
        saved = []
        for doc in sorted(self._dirty):
            projectio.write_yaml(self.path_for(doc), self._docs[doc])
            saved.append(doc)
        self._dirty.clear()
        return saved

    def discard(self) -> None:
        self._docs = {"presentation": None, "design": None, "layouts": None}
        self._dirty.clear()


def _default_furniture_value(
    element_id: str, field_name: str | None, design_data: dict[str, Any]
) -> dict[str, Any]:
    """A sensible starting box/style for a newly-added furniture item --
    the same "author refines from here" spirit `deckifyr init`'s own
    scaffold has, not a load-bearing design decision (spec section 7.8
    leaves exact placement entirely up to a project's own design.yaml).
    Sized relative to the project's own slide dimensions rather than a
    fixed widescreen assumption.
    """
    width_in, height_in = _slide_size_in(design_data)
    if element_id == FURNITURE_STATUS_ID and field_name == "watermark":
        box_w, box_h = width_in * 0.75, height_in * 0.25
        return {
            "box": _default_box((width_in - box_w) / 2, (height_in - box_h) / 2, box_w, box_h),
            "rotation": -30,
            "z_index": 9999,
        }
    if element_id == FURNITURE_STATUS_ID:
        margin = 0.25
        box_w, box_h = min(3.0, width_in * 0.3), 0.4
        x = margin if field_name in ("corner_tl", "corner_bl") else width_in - margin - box_w
        y = margin if field_name in ("corner_tr", "corner_tl") else height_in - margin - box_h
        return {"box": _default_box(x, y, box_w, box_h)}
    if element_id == FURNITURE_BRANDING_ID:
        box_w, box_h = min(3.0, width_in * 0.3), 0.35
        return {
            "text": "Organization Name",
            "box": _default_box(0.25, height_in - box_h - 0.2, box_w, box_h),
        }
    if element_id == FURNITURE_PAGE_NUMBER_ID:
        box_w, box_h = 0.8, 0.3
        return {
            "enabled": True,
            "format": "{page} / {total}",
            "box": _default_box(width_in - box_w - 0.25, height_in - box_h - 0.2, box_w, box_h),
        }
    raise HTTPException(status_code=404, detail=f"unknown furniture element {element_id!r}")


def _frontend_build_warning(static_dir: Path, web_src_dir: Path) -> str | None:
    """Dev-checkout-only staleness check for the committed frontend
    bundle under `static_dir` (`inst/python/deckifyr/web/static/`, spec
    section 12's own "committed generated output" posture, CLAUDE.md's
    "Web application" note), given the sibling frontend source tree
    `web_src_dir` (`<repo root>/web/src`). Real, previously-hit trap this
    exists to catch early instead of via a long confused debugging round:
    a genuine source fix in `web/src/` can sit uncompiled while a live
    `deckifyr serve` session keeps serving the old, pre-fix JS, and a
    browser hard-refresh alone does *not* help -- `StaticFiles` really is
    serving fresh bytes off disk each request, they're just still the
    stale ones, because nobody re-ran `npm run build` after the edit.

    `web_src_dir` is passed in (rather than derived from `__file__` here)
    specifically so this stays a pure, directly testable function --
    `create_app` is the one real call site, and it's also the one place
    that legitimately knows `web/src/` only exists in a real git checkout
    of this repo: an installed wheel/R package ships `inst/python`/
    `static/` alone, never the frontend source tree, so
    `web_src_dir.is_dir()` is `False` for every real end user and this is
    a silent, zero-cost no-op there, same as the rest of this module's
    dev-only concerns. Returns `None` when not a dev checkout, when
    there's no build to compare against yet is arguably a *build-missing*
    problem `static_dir.is_dir()` already handles elsewhere in
    `create_app`, or when the build is actually current; otherwise a
    short, actionable message.
    """
    if not web_src_dir.is_dir():
        return None

    def _latest_mtime(root: Path, suffixes: set[str]) -> float:
        return max(
            (
                p.stat().st_mtime
                for p in root.rglob("*")
                if p.is_file() and p.suffix in suffixes and ".test." not in p.name
            ),
            default=0.0,
        )

    source_mtime = _latest_mtime(web_src_dir, {".ts", ".tsx", ".css"})
    build_mtime = _latest_mtime(static_dir, {".js", ".css", ".html"}) if static_dir.is_dir() else 0.0
    if source_mtime <= build_mtime:
        return None
    return (
        "the built frontend under web/static/ is older than web/src/ -- "
        "run `npm run build` in web/ before trusting what this session "
        "serves; a browser hard-refresh alone will not pick up the "
        "missing rebuild."
    )


def _rebuild_frontend(web_dir: Path, *, timeout_seconds: float = 300.0) -> str | None:
    """Runs `npm run build` in `web_dir` (`web/`, the parent of
    `web_src_dir`) when `npm` is on PATH, so a stale committed bundle
    (`_frontend_build_warning` above) gets fixed automatically in a dev
    checkout instead of only ever being reported -- the actual answer to
    "why print a warning instead of just rebuilding" rather than a human
    having to run CONTRIBUTING.md's recipe by hand every time. Only
    `create_app` calls this, and only when that warning already fired;
    like `_frontend_build_warning` itself this is a silent no-op for every
    real end user (an installed wheel/R package has no `web/` to build).

    Returns `None` when there's nothing to report -- either `npm` isn't on
    PATH (caller falls back to the plain warning, unchanged from before
    this function existed) or the build succeeded -- otherwise a short
    message describing what went wrong, meant to be printed alongside
    (not instead of) the recomputed staleness warning. Never raises: a
    failed or timed-out auto-rebuild attempt must not crash `deckifyr
    serve` itself, since the manual `npm run build` recipe still works as
    a fallback either way.
    """
    npm = shutil.which("npm")
    if npm is None:
        return None
    print("deckifyr serve: frontend build is stale -- running `npm run build`...", file=sys.stderr)
    try:
        result = subprocess.run(
            [npm, "run", "build"],
            cwd=web_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return f"npm run build timed out after {timeout_seconds:.0f}s"
    except OSError as exc:
        return f"npm run build could not be started: {exc}"
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        return f"npm run build failed (exit {result.returncode}):\n{tail}"
    print("deckifyr serve: frontend rebuilt successfully.", file=sys.stderr)
    return None


def create_app(
    project_root: Path,
    presentation_name: str = "presentation.yaml",
    *,
    launcher: str = "cli",
) -> FastAPI:
    project_root = Path(project_root).resolve()
    presentation_path = project_root / presentation_name
    job_manager = JobManager()
    working_copy = _WorkingCopy(presentation_path)

    static_dir = Path(__file__).parent / "static"
    web_src_dir = Path(__file__).resolve().parents[4] / "web" / "src"
    frontend_warning = _frontend_build_warning(static_dir, web_src_dir)
    if frontend_warning is not None:
        rebuild_failure = _rebuild_frontend(web_src_dir.parent)
        if rebuild_failure is not None:
            print(f"deckifyr serve: WARNING: {rebuild_failure}", file=sys.stderr)
        frontend_warning = _frontend_build_warning(static_dir, web_src_dir)
    if frontend_warning is not None:
        print(f"deckifyr serve: WARNING: {frontend_warning}", file=sys.stderr)

    app = FastAPI(title="deckifyr")

    @app.exception_handler(DeckifyrError)
    async def _handle_deckifyr_error(request: Request, exc: DeckifyrError) -> JSONResponse:
        status_code = _ERROR_CODE_STATUS.get(exc.code, 500)
        return JSONResponse(status_code=status_code, content=exc.to_dict())

    def _load_presentation_doc() -> PresentationDocument:
        data = working_copy.get("presentation")
        try:
            return PresentationDocument.model_validate(data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(presentation_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc

    def _project_paths() -> tuple[Path, Path, Path]:
        return presentation_path, working_copy.path_for("design"), working_copy.path_for("layouts")

    def _doc_path(doc: str) -> Path:
        if doc not in projectio.DOCUMENT_MODELS:
            raise HTTPException(status_code=404, detail=f"unknown document type {doc!r}")
        return working_copy.path_for(doc)

    def _set_element_field(document: dict, path: str, value: Any) -> None:
        try:
            editor.set_value(document, path, value)
        except editor.PathError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.PATH_NOT_FOUND) from exc

    def _autosave_enabled() -> bool:
        presentation_data = working_copy.get("presentation") or {}
        build = presentation_data.get("build") or {}
        return bool(build.get("autosave", False))

    def _after_mutation() -> bool:
        """Call at the end of every mutating handler, after its edit has
        already been applied via `working_copy.set(...)`. Autosaves
        immediately when `presentation.yaml`'s `build.autosave` is on --
        this also covers flipping the checkbox itself with no special
        case, since the `PUT` that sets `autosave: true` is itself the
        mutation `_after_mutation` reacts to, and it's included in what
        gets flushed. Returns the `dirty` flag every mutating response
        carries.
        """
        if working_copy.dirty and _autosave_enabled():
            working_copy.save()
        return working_copy.dirty

    # --- health / project ------------------------------------------

    @app.get("/api/health")
    def get_health() -> dict[str, Any]:
        # `launcher` deliberately rides on /api/health, not /api/project:
        # it must be available even when the bound project itself fails to
        # load (that's exactly when the frontend's "no project found"
        # screen needs it, to show CLI- vs R-flavored next-step
        # instructions -- `presentation.yaml`/`design.yaml`/`layouts.yaml`
        # not existing yet is the whole point of that screen, so it can't
        # depend on a route that requires them).
        return {"status": "ok", "launcher": launcher, "frontend_warning": frontend_warning}

    @app.get("/api/project")
    def get_project() -> dict[str, Any]:
        _, design_path, layouts_path = _project_paths()
        return {
            "root": str(project_root),
            "presentation": str(presentation_path),
            "design": str(design_path),
            "layouts": str(layouts_path),
        }

    # --- config get/put ----------------------------------------------

    @app.get("/api/config/{doc}")
    def get_config(doc: str) -> Any:
        if doc not in projectio.DOCUMENT_MODELS:
            raise HTTPException(status_code=404, detail=f"unknown document type {doc!r}")
        return working_copy.get(doc)

    @app.put("/api/config/{doc}")
    def put_config(doc: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        path = _doc_path(doc)
        if doc == "presentation":
            presentation = projectio.validate_presentation_data(path, body)
            working_copy.set(doc, body)
            return {
                "path": str(path),
                "slide_count": len(presentation.slides),
                "dirty": _after_mutation(),
            }
        try:
            projectio.DOCUMENT_MODELS[doc].model_validate(body)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        working_copy.set(doc, body)
        return {"path": str(path), "dirty": _after_mutation()}

    # --- plan / validate ---------------------------------------------

    def _load_working_project() -> tuple[PresentationDocument, DesignDocument, Any]:
        return projectio.load_project(
            presentation_path,
            strict=True,
            presentation_data=working_copy.get("presentation"),
            design_data=working_copy.get("design"),
            layouts_data=working_copy.get("layouts"),
        )

    @app.get("/api/plan")
    def get_plan() -> dict[str, Any]:
        presentation, design, layouts = _load_working_project()
        resolved_slides = expand_presentation(presentation, design, layouts, strict=True)
        return {
            "slides": [_serialize_slide(slide) for slide in resolved_slides],
            "dirty": working_copy.dirty,
            # `slide.layout` per real slide id (issue #23's Layout tab) --
            # `ResolvedSlide` itself carries no `layout` field (spec's own
            # Pass 1/Pass 2 split, CLAUDE.md), so this is read straight off
            # `presentation.slides` rather than growing that shared
            # dataclass just for the web layer's own benefit.
            "slide_layouts": {slide.id: slide.layout for slide in presentation.slides},
        }

    @app.post("/api/validate")
    def post_validate() -> dict[str, Any]:
        presentation, design, layouts = _load_working_project()
        return {
            "valid": True,
            "presentation": str(presentation_path),
            "slide_count": len(presentation.slides),
            "layout_count": len(layouts.layouts),
            "schema_version": presentation.deckifyr,
        }

    # --- element editing -----------------------------------------------

    @app.patch("/api/slides/{slide_id}/elements/{element_id}")
    def patch_element(
        slide_id: str, element_id: str, body: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        data = working_copy.get("presentation")
        if not isinstance(data, dict) or "slides" not in data:
            raise DeckifyrError(
                f"{presentation_path} does not look like a presentation.yaml "
                "(no top-level 'slides' key)",
                code=ErrorCode.SCHEMA_VALIDATION,
            )
        edited = copy.deepcopy(data)
        slides = edited.get("slides") or []

        slide_index = next(
            (i for i, slide in enumerate(slides) if slide.get("id") == slide_id), None
        )
        if slide_index is None:
            raise HTTPException(status_code=404, detail=f"no slide with id {slide_id!r}")

        elements = slides[slide_index].get("elements")
        if isinstance(elements, dict):
            if element_id not in elements:
                raise HTTPException(
                    status_code=404,
                    detail=f"no element with id {element_id!r} on slide {slide_id!r}",
                )
            prefix = f"slides[{slide_index}].elements.{element_id}"
        elif isinstance(elements, list):
            element_index = next(
                (
                    i
                    for i, element in enumerate(elements)
                    if isinstance(element, dict) and element.get("id") == element_id
                ),
                None,
            )
            if element_index is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"no element with id {element_id!r} on slide {slide_id!r}",
                )
            prefix = f"slides[{slide_index}].elements[{element_index}]"
        else:
            raise HTTPException(
                status_code=404,
                detail=f"no element with id {element_id!r} on slide {slide_id!r}",
            )

        if "box" in body and body["box"]:
            for field_name, raw_value in body["box"].items():
                if field_name not in ("x", "y", "width", "height"):
                    continue
                # Box fields are stored as unit strings in YAML (e.g.
                # `"1.5in"`), not raw floats -- the frontend sends plain
                # inch numbers, so this is the one conversion point back
                # to what `Box`/`parse_length` (spec section 7.3) expect.
                _set_element_field(edited, f"{prefix}.box.{field_name}", f"{raw_value}in")
        if "rotation" in body:
            _set_element_field(edited, f"{prefix}.rotation", body["rotation"])
        if "z_index" in body:
            _set_element_field(edited, f"{prefix}.z_index", body["z_index"])
        if "value" in body:
            _set_element_field(edited, f"{prefix}.value", body["value"])

        presentation = projectio.validate_presentation_data(presentation_path, edited)
        working_copy.set("presentation", edited)
        return {
            "slide": slide_id,
            "element": element_id,
            "presentation": str(presentation_path),
            "slide_count": len(presentation.slides),
            "dirty": _after_mutation(),
        }

    # --- slide add/remove (issue #23) -----------------------------------
    #
    # Thin wrappers over `deckifyr.editor.add_slide`/`remove_slide`
    # (already real, unit-tested, and used by the CLI's own `slide add`/
    # `slide remove` subcommands) applied to the working copy's
    # `presentation.yaml` dict -- same validate-then-`working_copy.set`
    # shape every other mutating route here already uses, and the same
    # `DuplicateSlideIdError`/`SlideNotFoundError`/`AmbiguousPlacementError`
    # -> `DeckifyrError` code mapping `cli.py`'s `_cmd_slide_add`/
    # `_cmd_slide_move` already establish (`CONTENT_VALIDATION`/
    # `REFERENCE_NOT_FOUND`/`CONTENT_VALIDATION`, all 422 per
    # `_ERROR_CODE_STATUS`).

    @app.post("/api/slides")
    def add_slide(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        edited = copy.deepcopy(working_copy.get("presentation"))
        try:
            editor.add_slide(
                edited,
                id=body["id"],
                layout=body.get("layout"),
                index=body.get("index"),
                after=body.get("after"),
                before=body.get("before"),
            )
        except editor.DuplicateSlideIdError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
        except editor.SlideNotFoundError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
        except editor.AmbiguousPlacementError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.CONTENT_VALIDATION) from exc
        presentation = projectio.validate_presentation_data(presentation_path, edited)
        working_copy.set("presentation", edited)
        return {
            "id": body["id"],
            "slide_count": len(presentation.slides),
            "dirty": _after_mutation(),
        }

    @app.delete("/api/slides/{slide_id}")
    def remove_slide(slide_id: str) -> dict[str, Any]:
        edited = copy.deepcopy(working_copy.get("presentation"))
        try:
            editor.remove_slide(edited, slide_id)
        except editor.SlideNotFoundError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.REFERENCE_NOT_FOUND) from exc
        presentation = projectio.validate_presentation_data(presentation_path, edited)
        working_copy.set("presentation", edited)
        return {
            "id": slide_id,
            "slide_count": len(presentation.slides),
            "dirty": _after_mutation(),
        }

    # --- layout zones (issue #23's Content/Layout tab) -------------------
    #
    # A layout's own zones, resolved and edited the same way the
    # furniture pseudo-slide's own elements are: `GET /api/layouts/{name}`
    # reuses `expand_slide` with a synthetic, empty `Slide` (the same
    # trick `GET /api/furniture` already uses), and the PATCH route below
    # mirrors `patch_furniture_element`'s shape but targets `layouts.yaml`
    # instead of `design.yaml`. Unlike a slide's own `elements` (which may
    # be dict- or list-keyed, spec section 7.6), `Layout.elements` is
    # always dict-keyed, so there's no list-form branch to handle here.

    @app.get("/api/layouts/{layout_name}")
    def get_layout_zones(layout_name: str) -> dict[str, Any]:
        _presentation, _design, layouts = _load_working_project()
        if layout_name not in layouts.layouts:
            raise HTTPException(status_code=404, detail=f"unknown layout {layout_name!r}")
        design_data = working_copy.get("design") or {}
        elements = [
            _resolve_layout_zone(element_id, element, design_data, order)
            for order, (element_id, element) in enumerate(
                layouts.layouts[layout_name].elements.items()
            )
        ]
        elements.sort(key=lambda e: (e["z_index"], e["order"]))
        return {"id": f"__layout__{layout_name}", "notes": None, "elements": elements}

    @app.patch("/api/layouts/{layout_name}/elements/{element_id}")
    def patch_layout_element(
        layout_name: str, element_id: str, body: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        layouts_path = working_copy.path_for("layouts")
        edited = copy.deepcopy(working_copy.get("layouts"))
        prefix = f"layouts.{layout_name}.elements.{element_id}"
        try:
            editor.get_value(edited, prefix)
        except editor.PathError as exc:
            raise DeckifyrError(
                f"no zone {element_id!r} on layout {layout_name!r}",
                code=ErrorCode.PATH_NOT_FOUND,
            ) from exc

        if "box" in body and body["box"]:
            for field_name, raw_value in body["box"].items():
                if field_name not in ("x", "y", "width", "height"):
                    continue
                _set_element_field(edited, f"{prefix}.box.{field_name}", f"{raw_value}in")
        if "rotation" in body:
            _set_element_field(edited, f"{prefix}.rotation", body["rotation"])
        if "z_index" in body:
            _set_element_field(edited, f"{prefix}.z_index", body["z_index"])
        if "value" in body:
            _set_element_field(edited, f"{prefix}.value", body["value"])

        try:
            LayoutsDocument.model_validate(edited)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(layouts_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        working_copy.set("layouts", edited)
        return {
            "layout": layout_name,
            "element": element_id,
            "path": str(layouts_path),
            "dirty": _after_mutation(),
        }

    # --- furniture pseudo-slide (issue #21) -----------------------------

    @app.get("/api/furniture")
    def get_furniture() -> dict[str, Any]:
        presentation, design, _layouts = _load_working_project()
        synthetic_slide = Slide(id=FURNITURE_SLIDE_ID, layout=None)
        # `furniture_lenient=True`: this route's whole purpose is
        # authoring furniture, so a `status_indicator` selection with no
        # matching `furniture.status` style configured *yet* (or a bad
        # `page_number.format` placeholder) must not 500 the one screen
        # that could fix it -- see `_furniture_layout`'s own `lenient`
        # docstring. `GET /api/plan` (real-slide rendering) stays strict;
        # only this route relaxes.
        resolved = expand_slide(
            synthetic_slide,
            None,
            design,
            strict=True,
            page_number=1,
            total_pages=len(presentation.slides),
            status_indicator=presentation.status_indicator,
            corner_text=presentation.metadata.status,
            watermark_text=resolve_watermark_text(presentation),
            furniture_lenient=True,
        )
        return _serialize_slide(resolved)

    @app.patch("/api/furniture/elements/{element_id}")
    def patch_furniture_element(
        element_id: str, body: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        design_path = working_copy.path_for("design")
        prefix, allow_rotation, allow_z_index, text_field = _resolve_furniture_target(
            element_id, presentation_doc
        )

        edited = copy.deepcopy(working_copy.get("design"))
        try:
            target = editor.get_value(edited, prefix)
        except editor.PathError as exc:
            raise DeckifyrError(
                f"design.yaml's {prefix} isn't configured yet -- "
                f"POST /api/furniture/elements/{element_id} to add it first",
                code=ErrorCode.PATH_NOT_FOUND,
            ) from exc
        if target is None:
            raise DeckifyrError(
                f"design.yaml's {prefix} isn't configured yet -- "
                f"POST /api/furniture/elements/{element_id} to add it first",
                code=ErrorCode.PATH_NOT_FOUND,
            )

        if "box" in body and body["box"]:
            for field_name, raw_value in body["box"].items():
                if field_name not in ("x", "y", "width", "height"):
                    continue
                _set_element_field(edited, f"{prefix}.box.{field_name}", f"{raw_value}in")
        if "rotation" in body:
            if not allow_rotation:
                raise DeckifyrError(
                    f"design.yaml's {prefix} has no rotation field",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
            _set_element_field(edited, f"{prefix}.rotation", body["rotation"])
        if "z_index" in body:
            if not allow_z_index:
                raise DeckifyrError(
                    f"design.yaml's {prefix} has no z_index field",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
            _set_element_field(edited, f"{prefix}.z_index", body["z_index"])
        if "value" in body:
            if text_field is None:
                raise DeckifyrError(
                    f"design.yaml's {prefix} has no editable text here",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
            _set_element_field(edited, f"{prefix}.{text_field}", body["value"])

        try:
            DesignDocument.model_validate(edited)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(design_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        working_copy.set("design", edited)
        return {"element": element_id, "path": str(design_path), "dirty": _after_mutation()}

    @app.post("/api/furniture/elements/{element_id}")
    def add_furniture_element(element_id: str) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        design_path = working_copy.path_for("design")
        edited = copy.deepcopy(working_copy.get("design"))
        furniture = edited.setdefault("furniture", {})

        new_status_indicator: str | None = None
        if element_id == FURNITURE_STATUS_ID:
            indicator = presentation_doc.status_indicator
            if indicator is None or indicator == "none":
                # Nothing selected yet -- "Add" itself picks a default
                # placement (watermark, the simplest single-element
                # case) rather than requiring the Deck Options dropdown
                # to be touched first, mirroring
                # `DeckOptions.tsx`'s own `selectStatusIndicator`
                # collapsing select-and-configure into one action for
                # the dropdown path. Choosing a corner instead is still
                # one dropdown change away afterward.
                indicator = "watermark"
                new_status_indicator = indicator
            field_name = STATUS_INDICATOR_FIELDS[indicator]
            status_block = furniture.setdefault("status", {})
            if status_block.get(field_name) is not None:
                raise DeckifyrError(
                    f"design.yaml's furniture.status.{field_name} is already configured",
                    code=ErrorCode.SCHEMA_VALIDATION,
                )
            status_block[field_name] = _default_furniture_value(element_id, field_name, edited)
        elif element_id == FURNITURE_BRANDING_ID:
            if furniture.get("branding") is not None:
                raise DeckifyrError(
                    "design.yaml's furniture.branding is already configured",
                    code=ErrorCode.SCHEMA_VALIDATION,
                )
            furniture["branding"] = _default_furniture_value(element_id, None, edited)
        elif element_id == FURNITURE_PAGE_NUMBER_ID:
            if furniture.get("page_number") is not None:
                raise DeckifyrError(
                    "design.yaml's furniture.page_number is already configured",
                    code=ErrorCode.SCHEMA_VALIDATION,
                )
            furniture["page_number"] = _default_furniture_value(element_id, None, edited)
        elif element_id == FURNITURE_BACKGROUND_ID:
            raise DeckifyrError(
                "the background furniture item can't be added here -- set "
                "design.yaml's slide.background_image via the Config tab "
                "instead",
                code=ErrorCode.PATH_NOT_FOUND,
            )
        else:
            raise HTTPException(status_code=404, detail=f"unknown furniture element {element_id!r}")

        try:
            DesignDocument.model_validate(edited)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(design_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        if new_status_indicator is not None:
            # Validated *before* either write commits -- defaulting to
            # `"watermark"` with no text source anywhere (no `watermark`
            # override, no `metadata.status`) is exactly what
            # `_check_watermark_has_text` exists to reject, the same as
            # it always has for a `status_indicator: watermark` selected
            # via the Deck Options dropdown.
            edited_presentation = copy.deepcopy(working_copy.get("presentation"))
            edited_presentation["status_indicator"] = new_status_indicator
            projectio.validate_presentation_data(presentation_path, edited_presentation)
            working_copy.set("presentation", edited_presentation)
        working_copy.set("design", edited)
        return {"element": element_id, "path": str(design_path), "dirty": _after_mutation()}

    @app.delete("/api/furniture/elements/{element_id}")
    def remove_furniture_element(element_id: str) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        design_path = working_copy.path_for("design")
        edited = copy.deepcopy(working_copy.get("design"))
        furniture = edited.setdefault("furniture", {})

        presentation_updates: dict[str, Any] = {}
        if element_id == FURNITURE_STATUS_ID:
            indicator = presentation_doc.status_indicator
            if indicator is None or indicator == "none":
                raise DeckifyrError(
                    "no status indicator is selected -- choose one "
                    "in Deck Options first",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
            field_name = STATUS_INDICATOR_FIELDS[indicator]
            status_block = furniture.setdefault("status", {})
            status_block[field_name] = None
            # Removing the active placement also clears status_indicator
            # in the same action -- leaving it pointing at a style that
            # no longer exists is exactly the dangling-reference footgun
            # this route used to sidestep by refusing to expose Remove
            # at all.
            presentation_updates["status_indicator"] = None
        elif element_id == FURNITURE_BRANDING_ID:
            furniture["branding"] = None
        elif element_id == FURNITURE_PAGE_NUMBER_ID:
            furniture["page_number"] = None
        elif element_id == FURNITURE_BACKGROUND_ID:
            raise DeckifyrError(
                "the background furniture item can't be removed here -- "
                "clear design.yaml's slide.background_image via the "
                "Config tab instead",
                code=ErrorCode.PATH_NOT_FOUND,
            )
        else:
            raise HTTPException(status_code=404, detail=f"unknown furniture element {element_id!r}")

        # Unsetting a field to `None` can never fail `DesignDocument`
        # validation (every furniture sub-field is already `X | None`),
        # so this skips the validate-then-write try/except the other
        # routes need. Same reasoning for `presentation_updates`: every
        # field touched there is being set to `None`/`False`, which can
        # never trip `_check_watermark_has_text` (that validator only
        # ever rejects an *active* watermark with no text source).
        if presentation_updates:
            edited_presentation = copy.deepcopy(working_copy.get("presentation"))
            edited_presentation.update(presentation_updates)
            working_copy.set("presentation", edited_presentation)
        working_copy.set("design", edited)
        return {"element": element_id, "path": str(design_path), "dirty": _after_mutation()}

    # --- save / discard (issue #24) -------------------------------------

    @app.post("/api/save")
    def post_save() -> dict[str, Any]:
        saved = working_copy.save()
        return {"saved": saved, "dirty": working_copy.dirty}

    @app.post("/api/discard")
    def post_discard() -> dict[str, Any]:
        working_copy.discard()
        return {"dirty": working_copy.dirty}

    # --- build jobs ----------------------------------------------------

    @app.post("/api/build")
    def post_build() -> dict[str, Any]:
        job = job_manager.submit_build(project_root, presentation_name)
        return {"job_id": job.id}

    # --- preview (issue #27) --------------------------------------------

    @app.get("/api/preview/availability")
    def get_preview_availability() -> dict[str, Any]:
        """Proactive LibreOffice-availability check (issue #27: "with
        information there if they don't [have the appropriate
        binaries]") -- checked up front rather than only surfaced after a
        failed Preview click. Reads `build.preview.binary` off the
        working copy the same way `_build_preview_config`
        (`deckifyr.pptx.compose`) resolves it for a real build, defaulting
        to `"soffice"` unset.
        """
        presentation_data = working_copy.get("presentation") or {}
        preview_config = ((presentation_data.get("build") or {}).get("preview") or {})
        binary = preview_config.get("binary", "soffice")
        available = shutil.which(binary) is not None
        return {
            "available": available,
            "binary": binary,
            "display_name": "LibreOffice",
            "install_url": None if available else LIBREOFFICE_INSTALL_URL,
        }

    @app.post("/api/preview")
    def post_preview(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        slides = body.get("slides")
        job = job_manager.submit_preview(project_root, presentation_name, slides=slides)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job with id {job_id!r}")
        return {"id": job.id, "status": job.status, "result": job.result, "error": job.error}

    @app.get("/api/jobs/{job_id}/artifacts")
    def get_job_artifacts(job_id: str) -> dict[str, Any]:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job with id {job_id!r}")
        return {"artifacts": sorted(job.artifacts)}

    @app.get("/api/jobs/{job_id}/artifacts/{key}")
    def get_job_artifact(job_id: str, key: str) -> FileResponse:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job with id {job_id!r}")
        # Only ever a dict lookup -- never build a path from `key`
        # directly, so a request can't reach any file outside what this
        # job's own build actually produced (`jobs.py`'s own docstring).
        path = job.artifacts.get(key)
        if path is None:
            raise HTTPException(
                status_code=404, detail=f"no artifact {key!r} for job {job_id!r}"
            )
        return FileResponse(path)

    # --- schemas ---------------------------------------------------------

    @app.get("/api/schemas/{doc}")
    def get_schema(doc: str) -> dict[str, Any]:
        model = projectio.DOCUMENT_MODELS.get(doc)
        if model is None:
            raise HTTPException(status_code=404, detail=f"unknown document type {doc!r}")
        return model.model_json_schema()

    # --- static frontend, mounted last so /api/* always wins -----------

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:

        @app.get("/")
        def get_root() -> dict[str, str]:
            return {"message": "frontend not built - run `npm run build` in web/"}

    return app
