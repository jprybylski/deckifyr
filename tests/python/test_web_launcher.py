"""Launcher mode: dirty state on /api/health and an orderly stop (issue #83)."""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from deckifyr import cli
from deckifyr.web import app as web_app
from deckifyr.web.app import create_app


@pytest.fixture
def project_dir(minimal_deck_dir, tmp_path):
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path


def _make_dirty(client):
    data = client.get("/api/config/presentation").json()
    data["metadata"]["title"] = "Edited by the launcher test"
    assert client.put("/api/config/presentation", json=data).status_code == 200


class _Spy:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


@pytest.fixture
def stoppable(project_dir):
    spy = _Spy()
    app = create_app(project_dir, request_shutdown=spy)
    return TestClient(app), spy, app


# --- /api/health -----------------------------------------------------------


def test_health_reports_clean_state_and_no_jobs(stoppable):
    client, _, _ = stoppable
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["dirty"] is False
    assert body["active_jobs"] == 0


def test_health_dirty_flips_on_edit_and_clears_on_save(stoppable):
    client, _, _ = stoppable
    _make_dirty(client)
    assert client.get("/api/health").json()["dirty"] is True
    client.post("/api/save")
    assert client.get("/api/health").json()["dirty"] is False


def test_health_works_when_the_project_does_not_load(tmp_path):
    # No project files at all: readiness must never depend on loading one.
    body = TestClient(create_app(tmp_path, launcher="workspace")).get("/api/health").json()
    assert body["status"] == "ok"
    assert body["launcher"] == "workspace"
    assert body["dirty"] is False and body["active_jobs"] == 0


def test_health_reports_a_loaded_project(stoppable):
    client, _, _ = stoppable
    body = client.get("/api/health").json()
    assert body["project_loaded"] is True
    assert body["project_error"] is None


def test_health_reports_why_the_project_did_not_load_while_staying_200(tmp_path):
    response = TestClient(create_app(tmp_path, launcher="workspace")).get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["project_loaded"] is False
    assert body["project_error"]["code"] == "E_IO"
    assert "not found" in body["project_error"]["message"]


def test_health_reports_a_schema_error_in_the_project(project_dir):
    (project_dir / "presentation.yaml").write_text("deckifyr: '1'\nnonsense: true\n")
    body = TestClient(create_app(project_dir)).get("/api/health").json()
    assert body["project_loaded"] is False
    assert body["project_error"]["code"] == "E_SCHEMA_VALIDATION"


def test_health_poll_does_not_pin_a_cached_copy_of_the_project(project_dir):
    client = TestClient(create_app(project_dir))
    assert client.get("/api/health").json()["project_loaded"] is True
    # An on-disk change made after a health poll must still be what the first
    # real request sees: the probe must not have cached the pre-edit document.
    path = project_dir / "presentation.yaml"
    path.write_text(path.read_text().replace("Minimal Example Deck", "Edited After Health"))
    served = client.get("/api/config/presentation").json()
    assert served["metadata"]["title"] == "Edited After Health"


def test_health_counts_active_jobs(stoppable):
    client, _, app = stoppable
    app.state.job_manager._argv_prefix = (sys.executable, "-c", "import time; time.sleep(60)")
    job_id = client.post("/api/build").json()["job_id"]
    deadline = time.monotonic() + 10
    while client.get("/api/health").json()["active_jobs"] != 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.get("/api/health").json()["active_jobs"] == 1
    client.post(f"/api/jobs/{job_id}/cancel")
    assert client.get("/api/health").json()["active_jobs"] == 0


# --- POST /api/shutdown ----------------------------------------------------


def test_shutdown_with_nothing_to_lose_stops(stoppable):
    client, spy, _ = stoppable
    response = client.post("/api/shutdown")
    assert response.status_code == 200
    assert response.json() == {"status": "shutting_down", "saved": [], "cancelled_jobs": 0}
    assert spy.calls == 1


def test_shutdown_refuses_when_dirty_by_default_and_changes_nothing(stoppable, project_dir):
    client, spy, _ = stoppable
    _make_dirty(client)
    before = (project_dir / "presentation.yaml").read_text()

    response = client.post("/api/shutdown", json={})

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "E_SHUTDOWN_REFUSED"
    assert body["reasons"] == ["unsaved_changes"]
    assert spy.calls == 0
    assert (project_dir / "presentation.yaml").read_text() == before
    # Still running, still dirty -- nothing was saved or discarded.
    assert client.get("/api/health").json()["dirty"] is True


def test_shutdown_save_writes_the_edits_before_stopping(stoppable, project_dir):
    client, spy, _ = stoppable
    _make_dirty(client)

    response = client.post("/api/shutdown", json={"if_dirty": "save"})

    assert response.status_code == 200
    assert response.json()["saved"] == ["presentation"]
    assert spy.calls == 1
    assert "Edited by the launcher test" in (project_dir / "presentation.yaml").read_text()


def test_shutdown_refuses_while_jobs_run_unless_told_to_cancel(stoppable):
    client, spy, app = stoppable
    app.state.job_manager._argv_prefix = (sys.executable, "-c", "import time; time.sleep(60)")
    job_id = client.post("/api/build").json()["job_id"]
    deadline = time.monotonic() + 10
    while client.get(f"/api/jobs/{job_id}").json()["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.05)

    refused = client.post("/api/shutdown")
    assert refused.status_code == 409
    assert refused.json()["reasons"] == ["active_jobs"]
    assert spy.calls == 0
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "running"

    stopped = client.post("/api/shutdown", json={"active_jobs": "cancel"})
    assert stopped.status_code == 200
    assert stopped.json()["cancelled_jobs"] == 1
    assert spy.calls == 1
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"


def test_shutdown_refusal_reports_every_reason_without_side_effects(stoppable, project_dir):
    client, spy, app = stoppable
    app.state.job_manager._argv_prefix = (sys.executable, "-c", "import time; time.sleep(60)")
    job_id = client.post("/api/build").json()["job_id"]
    _make_dirty(client)
    before = (project_dir / "presentation.yaml").read_text()

    response = client.post("/api/shutdown", json={"if_dirty": "refuse"})

    assert response.status_code == 409
    assert response.json()["reasons"] == ["unsaved_changes", "active_jobs"]
    assert (project_dir / "presentation.yaml").read_text() == before
    assert spy.calls == 0
    client.post(f"/api/jobs/{job_id}/cancel")


@pytest.mark.parametrize("body", [{"if_dirty": "discard"}, {"active_jobs": "ignore"}])
def test_shutdown_rejects_unknown_modes(stoppable, body):
    client, spy, _ = stoppable
    assert client.post("/api/shutdown", json=body).status_code == 422
    assert spy.calls == 0


def test_shutdown_reports_it_cannot_stop_when_not_hosted_by_serve(project_dir):
    client = TestClient(create_app(project_dir))
    assert client.post("/api/shutdown").status_code == 501


# --- no npm under the workspace launcher ----------------------------------


def _stale(monkeypatch):
    calls = []
    monkeypatch.setattr(web_app, "_frontend_build_warning", lambda *a: "bundle is stale")
    monkeypatch.setattr(web_app, "_rebuild_frontend", lambda *a: calls.append(a) or None)
    return calls


def test_a_stale_dev_bundle_is_rebuilt_by_default(project_dir, monkeypatch):
    calls = _stale(monkeypatch)
    create_app(project_dir)
    assert len(calls) == 1


def test_frontend_rebuild_can_be_disabled(project_dir, monkeypatch, capsys):
    calls = _stale(monkeypatch)
    app = create_app(project_dir, allow_frontend_rebuild=False)
    assert calls == []
    # The staleness is still reported, just never "fixed" by shelling out.
    assert TestClient(app).get("/api/health").json()["frontend_warning"] == "bundle is stale"


@pytest.mark.parametrize(
    ("flags", "expect_allowed"),
    [
        ([], True),
        (["--launcher", "r"], True),
        (["--launcher", "workspace"], False),
        (["--no-frontend-rebuild"], False),
    ],
)
def test_serve_flags_decide_whether_npm_may_run(project_dir, monkeypatch, flags, expect_allowed):
    uvicorn = pytest.importorskip("uvicorn")
    captured = {}
    real_create_app = web_app.create_app

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_create_app(*args, **kwargs)

    class FakeServer:
        def __init__(self, config):
            pass

        def run(self):
            pass

    monkeypatch.setattr(web_app, "create_app", spy)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    assert cli.main(["serve", "--project", str(project_dir), *flags]) == 0
    assert captured["allow_frontend_rebuild"] is expect_allowed


# --- a real process: readiness, refuse, save, exit 0 -----------------------


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(port, method, path, payload=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = json.dumps(payload).encode() if payload is not None else None
    conn.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data) if data else None


@pytest.fixture
def served(project_dir):
    pytest.importorskip("uvicorn")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "deckifyr", "serve", "--project", str(project_dir),
         "--port", str(port), "--launcher", "workspace"],
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            status, body = _request(port, "GET", "/api/health")
            if status == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server never became ready")
    yield proc, port
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def test_real_process_refuse_then_save_then_exit_zero(served, project_dir):
    proc, port = served
    status, health = _request(port, "GET", "/api/health")
    assert health["launcher"] == "workspace" and health["dirty"] is False

    _, data = _request(port, "GET", "/api/config/presentation")
    data["metadata"]["title"] = "Saved on shutdown"
    assert _request(port, "PUT", "/api/config/presentation", data)[0] == 200
    assert _request(port, "GET", "/api/health")[1]["dirty"] is True

    status, body = _request(port, "POST", "/api/shutdown", {"if_dirty": "refuse"})
    assert status == 409 and body["code"] == "E_SHUTDOWN_REFUSED"
    assert proc.poll() is None, "a refused stop must leave the server running"
    assert _request(port, "GET", "/api/health")[0] == 200
    assert "Saved on shutdown" not in (project_dir / "presentation.yaml").read_text()

    started = time.monotonic()
    status, body = _request(port, "POST", "/api/shutdown", {"if_dirty": "save"})
    assert status == 200
    assert proc.wait(timeout=15) == 0
    assert time.monotonic() - started < 10
    assert "Saved on shutdown" in (project_dir / "presentation.yaml").read_text()


def test_real_process_clean_stop_exits_zero_quickly(served):
    proc, port = served
    started = time.monotonic()
    assert _request(port, "POST", "/api/shutdown")[0] == 200
    assert proc.wait(timeout=15) == 0
    assert time.monotonic() - started < 10
    assert "unsaved" not in (proc.stderr.read() or "")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_real_process_sigterm_with_unsaved_edits_warns_instead_of_losing_them_silently(
    served, project_dir
):
    proc, port = served
    _, data = _request(port, "GET", "/api/config/presentation")
    data["metadata"]["title"] = "Never saved"
    assert _request(port, "PUT", "/api/config/presentation", data)[0] == 200

    proc.terminate()
    # uvicorn drains, then re-raises the captured SIGTERM (so the exit is
    # by-signal, not 0) -- the warning must already have been written.
    assert proc.wait(timeout=15) in (0, -15)

    assert "unsaved changes" in proc.stderr.read()
    # Still not written: SIGTERM can't ask "save?", it can only say so.
    assert "Never saved" not in (project_dir / "presentation.yaml").read_text()


def test_stopping_the_server_cancels_leftover_jobs_instead_of_orphaning_them(project_dir, capsys):
    app = create_app(project_dir, request_shutdown=_Spy())
    app.state.job_manager._argv_prefix = (sys.executable, "-c", "import time; time.sleep(60)")
    with TestClient(app) as client:
        job_id = client.post("/api/build").json()["job_id"]
        deadline = time.monotonic() + 10
        while client.get(f"/api/jobs/{job_id}").json()["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.05)
    # Leaving the `with` ran the app's shutdown lifespan.
    assert app.state.job_manager.get(job_id).status == "cancelled"
    assert "still running" in capsys.readouterr().err
