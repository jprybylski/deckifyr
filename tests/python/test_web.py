import shutil
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from pptx import Presentation

from deckifyr.schema.presentation import PresentationDocument
from deckifyr.web.app import create_app


def _copy_minimal_deck(minimal_deck_dir, tmp_path):
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def project_dir(minimal_deck_dir, tmp_path):
    return _copy_minimal_deck(minimal_deck_dir, tmp_path)


@pytest.fixture
def client(project_dir):
    app = create_app(project_dir)
    return TestClient(app)


# --- health / project --------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    # `launcher` defaults to "cli" -- see test_health_reports_r_launcher
    # for create_app(..., launcher="r").
    assert response.json() == {"status": "ok", "launcher": "cli"}


def test_health_reports_r_launcher(tmp_path):
    # /api/health must carry `launcher` even when the bound project fails
    # to load (an empty tmp_path, no presentation.yaml) -- it's the one
    # route the "no project found" screen can rely on to pick CLI- vs
    # R-flavored next-step instructions, precisely when /api/project
    # itself 404s.
    app = create_app(tmp_path, launcher="r")
    with TestClient(app) as local_client:
        response = local_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "launcher": "r"}


def test_project_reports_bound_paths(client, project_dir):
    response = client.get("/api/project")
    assert response.status_code == 200
    body = response.json()
    assert body["root"] == str(project_dir.resolve())
    assert body["presentation"].endswith("presentation.yaml")
    assert body["design"].endswith("design.yaml")
    assert body["layouts"].endswith("layouts.yaml")


# --- config get/put ------------------------------------------------------


def test_get_config_design(client):
    response = client.get("/api/config/design")
    assert response.status_code == 200
    assert response.json()["colors"]["primary"] == "#2457A6"


def test_get_config_unknown_doc_is_404(client):
    response = client.get("/api/config/nope")
    assert response.status_code == 404


def test_put_config_design_valid_edit_round_trips(client, project_dir):
    design_path = project_dir / "design.yaml"
    data = yaml.safe_load(design_path.read_text())
    data["colors"]["primary"] = "#123456"

    response = client.put("/api/config/design", json=data)
    assert response.status_code == 200

    on_disk = yaml.safe_load(design_path.read_text())
    assert on_disk["colors"]["primary"] == "#123456"

    response = client.get("/api/config/design")
    assert response.json()["colors"]["primary"] == "#123456"


def test_put_config_design_invalid_edit_is_422_and_file_unchanged(client, project_dir):
    design_path = project_dir / "design.yaml"
    original = design_path.read_text()
    data = yaml.safe_load(original)
    # `slide.width` is required -- dropping it breaks schema validation.
    del data["slide"]["width"]

    response = client.put("/api/config/design", json=data)
    assert response.status_code == 422
    body = response.json()
    assert "code" in body and "message" in body

    assert design_path.read_text() == original


def test_put_config_presentation_invalid_layout_reference_is_422(client, project_dir):
    presentation_path = project_dir / "presentation.yaml"
    original = presentation_path.read_text()
    data = yaml.safe_load(original)
    data["slides"][1]["layout"] = "does-not-exist"

    response = client.put("/api/config/presentation", json=data)
    assert response.status_code == 422
    assert presentation_path.read_text() == original


# --- plan ------------------------------------------------------------------


def test_plan_has_expected_slide_and_element_shape_with_formatted_geometry(client):
    response = client.get("/api/plan")
    assert response.status_code == 200
    body = response.json()

    slides = body["slides"]
    assert len(slides) == 2
    assert slides[0]["id"] == "title"

    elements = slides[0]["elements"]
    assert any(el["id"] == "deck-title" for el in elements)
    deck_title = next(el for el in elements if el["id"] == "deck-title")

    # Geometry is formatted through `format_length` as unit strings, not
    # raw EMU ints -- the box the minimal deck fixture declares is
    # `{x: 0.9in, y: 2.1in, width: 11.5in, height: 1.1in}`.
    assert deck_title["box"] == {
        "x": "0.9in",
        "y": "2.1in",
        "width": "11.5in",
        "height": "1.1in",
    }
    assert "x" not in deck_title
    assert "width" not in deck_title


# --- element PATCH -----------------------------------------------------


def test_patch_element_box_and_rotation_updates_file_and_response(client, project_dir):
    response = client.patch(
        "/api/slides/title/elements/deck-title",
        json={"box": {"x": 1.0, "y": 2.5}, "rotation": 15},
    )
    assert response.status_code == 200

    data = yaml.safe_load((project_dir / "presentation.yaml").read_text())
    element = data["slides"][0]["elements"][0]
    assert element["id"] == "deck-title"
    assert element["box"]["x"] == "1.0in"
    assert element["box"]["y"] == "2.5in"
    assert element["rotation"] == 15


def test_patch_element_unknown_slide_is_404(client):
    response = client.patch(
        "/api/slides/does-not-exist/elements/deck-title", json={"rotation": 5}
    )
    assert response.status_code == 404


def test_patch_element_unknown_element_is_404(client):
    response = client.patch(
        "/api/slides/title/elements/does-not-exist", json={"rotation": 5}
    )
    assert response.status_code == 404


def test_patch_element_invalid_value_is_422_and_file_unchanged(client, project_dir):
    presentation_path = project_dir / "presentation.yaml"
    original = presentation_path.read_text()

    # `rotation` is a float field -- a non-numeric value fails schema
    # validation (unlike a negative box dimension, which `Box`'s plain
    # `str` fields don't reject at this layer at all).
    response = client.patch(
        "/api/slides/title/elements/deck-title", json={"rotation": "sideways"}
    )
    assert response.status_code == 422

    assert presentation_path.read_text() == original


# --- build job lifecycle ----------------------------------------------


def test_build_job_lifecycle(client):
    response = client.post("/api/build")
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    status = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/jobs/{job_id}")
        assert job_response.status_code == 200
        status = job_response.json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.25)

    job_body = job_response.json()
    assert status == "succeeded", job_body
    assert job_body["result"] is not None
    assert job_body["error"] is None

    artifacts_response = client.get(f"/api/jobs/{job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifact_keys = artifacts_response.json()["artifacts"]
    assert "pptx" in artifact_keys

    pptx_response = client.get(f"/api/jobs/{job_id}/artifacts/pptx")
    assert pptx_response.status_code == 200
    assert len(pptx_response.content) > 0
    # A real, readable .pptx package -- not just nonzero bytes.
    import io

    Presentation(io.BytesIO(pptx_response.content))

    missing_response = client.get(f"/api/jobs/{job_id}/artifacts/nonexistent-key")
    assert missing_response.status_code == 404


def test_job_not_found_is_404(client):
    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404


# --- schemas -------------------------------------------------------------


def test_schema_presentation_matches_model(client):
    response = client.get("/api/schemas/presentation")
    assert response.status_code == 200
    assert response.json() == PresentationDocument.model_json_schema()


def test_schema_unknown_doc_is_404(client):
    response = client.get("/api/schemas/nope")
    assert response.status_code == 404
