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
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import DeckifyrError, ErrorCode
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
                "no status/watermark placement is selected -- choose one "
                "in Deck Options first",
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
    if element_id == FURNITURE_STATUS_ID:
        if field_name == "watermark":
            box_w, box_h = width_in * 0.75, height_in * 0.25
            return {
                "box": _default_box(
                    (width_in - box_w) / 2, (height_in - box_h) / 2, box_w, box_h
                ),
                "rotation": -30,
                "z_index": 9999,
            }
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


def create_app(
    project_root: Path,
    presentation_name: str = "presentation.yaml",
    *,
    launcher: str = "cli",
) -> FastAPI:
    project_root = Path(project_root).resolve()
    presentation_path = project_root / presentation_name
    job_manager = JobManager()

    app = FastAPI(title="deckifyr")

    @app.exception_handler(DeckifyrError)
    async def _handle_deckifyr_error(request: Request, exc: DeckifyrError) -> JSONResponse:
        status_code = _ERROR_CODE_STATUS.get(exc.code, 500)
        return JSONResponse(status_code=status_code, content=exc.to_dict())

    def _load_presentation_doc() -> PresentationDocument:
        data = projectio.read_yaml(presentation_path)
        try:
            return PresentationDocument.model_validate(data)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(presentation_path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc

    def _project_paths() -> tuple[Path, Path, Path]:
        presentation = _load_presentation_doc()
        design_path = (presentation_path.parent / presentation.design.base).resolve()
        layouts_path = (presentation_path.parent / presentation.layouts).resolve()
        return presentation_path, design_path, layouts_path

    def _doc_path(doc: str) -> Path:
        if doc not in projectio.DOCUMENT_MODELS:
            raise HTTPException(status_code=404, detail=f"unknown document type {doc!r}")
        _, design_path, layouts_path = _project_paths()
        return {
            "design": design_path,
            "layouts": layouts_path,
            "presentation": presentation_path,
        }[doc]

    def _set_element_field(document: dict, path: str, value: Any) -> None:
        try:
            editor.set_value(document, path, value)
        except editor.PathError as exc:
            raise DeckifyrError(str(exc), code=ErrorCode.PATH_NOT_FOUND) from exc

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
        return {"status": "ok", "launcher": launcher}

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
        return projectio.read_yaml(_doc_path(doc))

    @app.put("/api/config/{doc}")
    def put_config(doc: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        path = _doc_path(doc)
        if doc == "presentation":
            return projectio.validate_and_write_presentation(path, body)
        try:
            projectio.DOCUMENT_MODELS[doc].model_validate(body)
        except PydanticValidationError as exc:
            raise DeckifyrError(
                projectio.format_pydantic_error(exc, str(path)),
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        projectio.write_yaml(path, body)
        return {"path": str(path)}

    # --- plan / validate ---------------------------------------------

    @app.get("/api/plan")
    def get_plan() -> dict[str, Any]:
        presentation, design, layouts = projectio.load_project(presentation_path, strict=True)
        resolved_slides = expand_presentation(presentation, design, layouts, strict=True)
        return {"slides": [_serialize_slide(slide) for slide in resolved_slides]}

    @app.post("/api/validate")
    def post_validate() -> dict[str, Any]:
        presentation, design, layouts = projectio.load_project(presentation_path, strict=True)
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
        data = projectio.load_presentation_raw(presentation_path)
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

        result = projectio.validate_and_write_presentation(presentation_path, edited)
        return {"slide": slide_id, "element": element_id, **result}

    # --- furniture pseudo-slide (issue #21) -----------------------------

    @app.get("/api/furniture")
    def get_furniture() -> dict[str, Any]:
        presentation, design, _layouts = projectio.load_project(presentation_path, strict=True)
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
            watermark_text=resolve_watermark_text(presentation),
            furniture_lenient=True,
        )
        return _serialize_slide(resolved)

    @app.patch("/api/furniture/elements/{element_id}")
    def patch_furniture_element(
        element_id: str, body: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        _, design_path, _ = _project_paths()
        prefix, allow_rotation, allow_z_index, text_field = _resolve_furniture_target(
            element_id, presentation_doc
        )

        edited = copy.deepcopy(projectio.read_yaml(design_path))
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
        projectio.write_yaml(design_path, edited)
        return {"element": element_id, "path": str(design_path)}

    @app.post("/api/furniture/elements/{element_id}")
    def add_furniture_element(element_id: str) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        _, design_path, _ = _project_paths()
        edited = copy.deepcopy(projectio.read_yaml(design_path))
        furniture = edited.setdefault("furniture", {})

        if element_id == FURNITURE_STATUS_ID:
            indicator = presentation_doc.status_indicator
            if indicator is None or indicator == "none":
                raise DeckifyrError(
                    "no status/watermark placement is selected -- choose "
                    "one in Deck Options first",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
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
        projectio.write_yaml(design_path, edited)
        return {"element": element_id, "path": str(design_path)}

    @app.delete("/api/furniture/elements/{element_id}")
    def remove_furniture_element(element_id: str) -> dict[str, Any]:
        presentation_doc = _load_presentation_doc()
        _, design_path, _ = _project_paths()
        edited = copy.deepcopy(projectio.read_yaml(design_path))
        furniture = edited.setdefault("furniture", {})

        if element_id == FURNITURE_STATUS_ID:
            indicator = presentation_doc.status_indicator
            if indicator is None or indicator == "none":
                raise DeckifyrError(
                    "no status/watermark placement is selected -- choose "
                    "one in Deck Options first",
                    code=ErrorCode.PATH_NOT_FOUND,
                )
            field_name = STATUS_INDICATOR_FIELDS[indicator]
            status_block = furniture.setdefault("status", {})
            status_block[field_name] = None
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
        # routes need.
        projectio.write_yaml(design_path, edited)
        return {"element": element_id, "path": str(design_path)}

    # --- build jobs ----------------------------------------------------

    @app.post("/api/build")
    def post_build() -> dict[str, Any]:
        job = job_manager.submit_build(project_root, presentation_name)
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

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:

        @app.get("/")
        def get_root() -> dict[str, str]:
            return {"message": "frontend not built - run `npm run build` in web/"}

    return app
