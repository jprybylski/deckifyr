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
from deckifyr.plan import ResolvedElement, ResolvedSlide, expand_presentation
from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.units import format_length
from deckifyr.web.jobs import JobManager

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


def create_app(project_root: Path, presentation_name: str = "presentation.yaml") -> FastAPI:
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
        return {"status": "ok"}

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
