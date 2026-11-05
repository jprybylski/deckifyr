"""Trusted binaries and project-path containment (issue #89).

The point of every test here is "nothing ran / nothing was read": a stub
executable records that it was started, and each rejection case is paired
with a control that *does* start it, so a passing test proves the policy --
not a broken stub -- is what stopped it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from deckifyr.cli import EXIT_OK, main
from deckifyr.policy import (
    PERMISSIVE,
    TrustPolicy,
    check_binary_trust,
    default_binary,
    resolve_in_project,
    resolve_policy,
)
from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.web.app import create_app
from deckifyr.web.jobs import JobManager

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang scripts")

TRUST = TrustPolicy(trusted_binaries_only=True)


@pytest.fixture
def deck(minimal_deck_dir, tmp_path):
    """A writable copy of the minimal deck inside its own project directory."""
    root = tmp_path / "project"
    root.mkdir()
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, root / name)
    return root


def _edit(deck: Path, mutate) -> Path:
    path = deck / "presentation.yaml"
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _run(capsys, *argv, env=None, monkeypatch=None):
    if env and monkeypatch:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
    code = main(["--json", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _stub_binary(tmp_path: Path, name: str = "stub-soffice") -> tuple[Path, Path]:
    """An executable that records it ran, then fails (so no real work follows)."""
    marker = tmp_path / f"{name}.ran"
    script = tmp_path / name
    script.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'w').write('ran')\nraise SystemExit(1)\n")
    script.chmod(0o755)
    return script, marker


# --- resolve_policy: flag > environment > off --------------------------------


def test_policy_is_off_by_default():
    policy = resolve_policy(SimpleNamespace(), {})
    assert policy == PERMISSIVE
    assert not policy.contain_paths and policy.to_argv() == []


def test_flags_beat_environment_and_environment_fills_the_rest():
    args = SimpleNamespace(quarto_bin="/flag/quarto", trusted_binaries_only=False)
    env = {
        "DECKIFYR_QUARTO_BIN": "/env/quarto",
        "DECKIFYR_SOFFICE_BIN": "/env/soffice",
        "DECKIFYR_TRUSTED_BINARIES_ONLY": "true",
        "DECKIFYR_ALLOW_OUTSIDE_PROJECT": "0",
    }
    policy = resolve_policy(args, env)
    assert policy.quarto_bin == "/flag/quarto"
    assert policy.soffice_bin == "/env/soffice"
    assert policy.rscript_bin is None
    assert policy.trusted_binaries_only is True
    assert policy.allow_outside_project is False


def test_to_argv_recreates_the_policy_for_a_child_process():
    policy = TrustPolicy(
        quarto_bin="/q", soffice_bin="/s", trusted_binaries_only=True, allow_outside_project=True
    )
    assert policy.to_argv() == [
        "--quarto-bin", "/q", "--soffice-bin", "/s",
        "--trusted-binaries-only", "--allow-outside-project",
    ]


def test_default_binaries_come_from_the_schema_models():
    assert default_binary("quarto") == "quarto"
    assert default_binary("soffice") == "soffice"
    assert default_binary("rscript") == "Rscript"


def test_containment_rides_on_trusted_binaries_only_and_can_be_relaxed():
    assert not TrustPolicy().contain_paths
    assert not TrustPolicy(allow_outside_project=True).contain_paths
    assert TrustPolicy(trusted_binaries_only=True).contain_paths
    assert not TrustPolicy(trusted_binaries_only=True, allow_outside_project=True).contain_paths


# --- check_binary_trust ------------------------------------------------------


def _presentation(minimal_deck_dir, **build) -> PresentationDocument:
    data = yaml.safe_load((minimal_deck_dir / "presentation.yaml").read_text())
    data["build"].update(build)
    return PresentationDocument.model_validate(data)


@pytest.mark.parametrize(
    "build, field",
    [
        ({"quarto": {"binary": "/tmp/x"}}, "build.quarto.binary"),
        ({"preview": {"binary": "/tmp/x"}}, "build.preview.binary"),
        ({"reportifyr": {"flextable": {"binary": "/tmp/x"}}}, "build.reportifyr.flextable.binary"),
    ],
)
def test_a_non_default_binary_is_untrusted_under_the_policy(minimal_deck_dir, build, field):
    presentation = _presentation(minimal_deck_dir, **build)
    check_binary_trust(presentation, PERMISSIVE)  # fine without the policy
    with pytest.raises(DeckifyrError) as excinfo:
        check_binary_trust(presentation, TRUST)
    assert excinfo.value.code == ErrorCode.UNTRUSTED_BINARY
    assert field in str(excinfo.value)


def test_the_default_bare_name_and_an_overridden_binary_are_trusted(minimal_deck_dir):
    check_binary_trust(_presentation(minimal_deck_dir, quarto={"binary": "quarto"}), TRUST)
    # The override wins and the project's value is never used, so it is not an error.
    overridden = TrustPolicy(trusted_binaries_only=True, quarto_bin="/launcher/quarto")
    check_binary_trust(_presentation(minimal_deck_dir, quarto={"binary": "/tmp/x"}), overridden)


# --- resolve_in_project ------------------------------------------------------


def test_resolve_in_project_catches_dotdot_absolute_and_symlinks(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True) if sys.platform != "win32" else None

    assert resolve_in_project(root, "design.yaml", "f", TRUST) == (root / "design.yaml").resolve()
    for bad in ("../outside/x.yaml", str(outside / "x.yaml")):
        with pytest.raises(DeckifyrError) as excinfo:
            resolve_in_project(root, bad, "design.base", TRUST)
        assert excinfo.value.code == ErrorCode.PATH_OUTSIDE_PROJECT
        # ...but allowed with no policy / with the explicit opt-out.
        resolve_in_project(root, bad, "design.base", PERMISSIVE)
        resolve_in_project(root, bad, "design.base", TrustPolicy(True, allow_outside_project=True))
    if sys.platform != "win32":
        with pytest.raises(DeckifyrError):  # a symlink inside the project pointing out of it
            resolve_in_project(root, "link/x.yaml", "layouts", TRUST)


# --- CLI: nothing runs under --trusted-binaries-only ------------------------


@posix_only
def test_an_untrusted_binary_fails_validate_and_build_and_nothing_runs(deck, tmp_path, capsys):
    stub, marker = _stub_binary(tmp_path)
    path = _edit(deck, lambda d: d["build"].update(previews=True, preview={"binary": str(stub)}))

    # Control: without the policy the stub IS reachable (the preview step runs it).
    code, _, _ = _run(capsys, "build", str(path))
    assert code != EXIT_OK and marker.exists(), "stub should be reachable without the policy"
    marker.unlink()

    for command in ("validate", "build", "preview"):
        code, out, err = _run(capsys, command, "--trusted-binaries-only", str(path))
        assert code != EXIT_OK and out == "", command
        payload = json.loads(err)
        assert payload["code"] == "E_UNTRUSTED_BINARY", command
        assert "build.preview.binary" in payload["message"]
        assert not marker.exists(), f"{command} ran the project file's binary"


@posix_only
def test_a_binary_flag_overrides_the_project_file(deck, tmp_path, capsys):
    stub, marker = _stub_binary(tmp_path)
    path = _edit(deck, lambda d: d["build"].update(previews=True, preview={"binary": "/definitely/not/here"}))

    _run(capsys, "build", "--soffice-bin", str(stub), "--trusted-binaries-only", str(path))

    assert marker.exists(), "the launcher's --soffice-bin should have been run, not the file's"


@posix_only
def test_a_binary_env_var_overrides_the_project_file(deck, tmp_path, capsys, monkeypatch):
    stub, marker = _stub_binary(tmp_path)
    path = _edit(deck, lambda d: d["build"].update(previews=True, preview={"binary": "/definitely/not/here"}))
    monkeypatch.setenv("DECKIFYR_SOFFICE_BIN", str(stub))

    _run(capsys, "build", str(path))

    assert marker.exists()


def test_the_edit_commands_see_the_policy_through_the_environment(deck, capsys, monkeypatch):
    path = deck / "presentation.yaml"
    before = path.read_text()
    monkeypatch.setenv("DECKIFYR_TRUSTED_BINARIES_ONLY", "1")

    code, _, err = _run(capsys, "set", str(path), "build.quarto", '{"binary": "/tmp/x"}')

    assert code != EXIT_OK and json.loads(err)["code"] == "E_UNTRUSTED_BINARY"
    assert path.read_text() == before  # rejected before anything was written


# --- CLI: containment --------------------------------------------------------


def test_outside_paths_are_allowed_by_default_so_existing_projects_are_unchanged(
    deck, tmp_path, capsys
):
    shutil.copyfile(deck / "design.yaml", tmp_path / "shared-design.yaml")
    path = _edit(deck, lambda d: d["design"].update(base="../shared-design.yaml"))

    code, out, _ = _run(capsys, "validate", str(path))

    assert code == EXIT_OK and json.loads(out)["valid"] is True


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda d: d["design"].update(base="../shared-design.yaml"), "design.base"),
        (lambda d: d.update(layouts="../shared-layouts.yaml"), "layouts"),
        (lambda d: d["build"].update(output="../escaped.pptx"), "build.output"),
        (lambda d: d["build"].update(manifest="../escaped.json"), "build.manifest"),
        (lambda d: d["build"].update(reportifyr={"outputs_dir": "../OUTPUTS"}), "outputs_dir"),
    ],
)
def test_trusted_mode_rejects_a_path_outside_the_project(deck, tmp_path, capsys, mutate, field):
    shutil.copyfile(deck / "design.yaml", tmp_path / "shared-design.yaml")
    shutil.copyfile(deck / "layouts.yaml", tmp_path / "shared-layouts.yaml")
    path = _edit(deck, mutate)

    for command in ("validate", "build"):
        code, out, err = _run(capsys, command, "--trusted-binaries-only", str(path))
        assert code != EXIT_OK and out == "", command
        payload = json.loads(err)
        assert payload["code"] == "E_PATH_OUTSIDE_PROJECT", command
        assert field in payload["message"]
    assert not (tmp_path / "escaped.pptx").exists() and not (tmp_path / "escaped.json").exists()

    # The explicit opt-out restores it (for a launcher with a shared design).
    code, _, _ = _run(
        capsys, "validate", "--trusted-binaries-only", "--allow-outside-project", str(path)
    )
    assert code == EXIT_OK


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_trusted_mode_follows_symlinks_out_of_the_project(deck, tmp_path, capsys):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    shutil.copyfile(deck / "layouts.yaml", outside / "layouts.yaml")
    (deck / "linked").symlink_to(outside, target_is_directory=True)
    path = _edit(deck, lambda d: d.update(layouts="linked/layouts.yaml"))

    code, _, err = _run(capsys, "validate", "--trusted-binaries-only", str(path))

    assert code != EXIT_OK and json.loads(err)["code"] == "E_PATH_OUTSIDE_PROJECT"


# --- the editor ----------------------------------------------------------------


@pytest.fixture
def trusted_client(deck):
    return TestClient(create_app(deck, policy=TRUST))


def _presentation_json(client):
    return client.get("/api/config/presentation").json()


def test_editor_put_rejects_an_untrusted_binary_and_changes_nothing(trusted_client, deck):
    body = _presentation_json(trusted_client)
    body["build"]["quarto"] = {"binary": "/tmp/x"}

    response = trusted_client.put("/api/config/presentation", json=body)

    assert response.status_code == 422
    assert "E_UNTRUSTED_BINARY" in response.text
    assert trusted_client.get("/api/health").json()["dirty"] is False
    assert "quarto" not in (_presentation_json(trusted_client)["build"])


def test_editor_put_rejects_an_outside_path_and_save_never_writes_there(trusted_client, deck, tmp_path):
    body = _presentation_json(trusted_client)
    body["design"]["base"] = "../../elsewhere.yaml"

    response = trusted_client.put("/api/config/presentation", json=body)

    assert response.status_code == 422 and "E_PATH_OUTSIDE_PROJECT" in response.text
    assert trusted_client.post("/api/save").status_code == 200
    assert not (tmp_path.parent / "elsewhere.yaml").exists()


def test_editor_put_allows_outside_paths_without_a_policy(deck, tmp_path):
    shutil.copyfile(deck / "design.yaml", tmp_path / "shared-design.yaml")
    client = TestClient(create_app(deck))  # default: unchanged behaviour
    body = _presentation_json(client)
    body["design"]["base"] = "../shared-design.yaml"

    assert client.put("/api/config/presentation", json=body).status_code == 200


def test_editor_never_reads_a_design_outside_the_project_under_the_policy(deck, tmp_path):
    secret = tmp_path / "secret.yaml"
    secret.write_text("UNIQUE-SECRET-CONTENT: 1\n")
    _edit(deck, lambda d: d["design"].update(base="../secret.yaml"))
    client = TestClient(create_app(deck, policy=TRUST))

    response = client.get("/api/config/design")

    assert response.status_code == 422 and "E_PATH_OUTSIDE_PROJECT" in response.text
    assert "UNIQUE-SECRET-CONTENT" not in response.text
    health = client.get("/api/health").json()
    assert health["project_loaded"] is False
    assert health["project_error"]["code"] == "E_PATH_OUTSIDE_PROJECT"


def test_preview_availability_reports_the_launchers_binary(deck):
    path = _edit(deck, lambda d: d["build"].update(preview={"binary": "/project/file/soffice"}))
    assert path.is_file()
    overridden = TestClient(create_app(deck, policy=TrustPolicy(soffice_bin=sys.executable)))
    body = overridden.get("/api/preview/availability").json()
    assert body["binary"] == sys.executable and body["available"] is True

    plain = TestClient(create_app(deck)).get("/api/preview/availability").json()
    assert plain["binary"] == "/project/file/soffice"


def test_the_policy_is_carried_into_the_job_subprocesses(tmp_path):
    echo = "import json, sys; print(json.dumps({'status': 'ok', 'argv': sys.argv[1:]}))"
    manager = JobManager(
        argv_prefix=[sys.executable, "-c", echo],
        policy_argv=TrustPolicy(quarto_bin="/q", trusted_binaries_only=True).to_argv(),
    )
    job = manager.submit_build(tmp_path, "presentation.yaml")
    import time

    deadline = time.monotonic() + 15
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.status == "succeeded"
    assert job.result["argv"] == [
        "build", "presentation.yaml", "--quarto-bin", "/q", "--trusted-binaries-only",
    ]


def test_create_app_hands_its_policy_to_the_job_manager(deck):
    app = create_app(deck, policy=TrustPolicy(soffice_bin="/s", trusted_binaries_only=True))
    assert app.state.job_manager._policy_argv == ("--soffice-bin", "/s", "--trusted-binaries-only")


def test_serve_builds_its_policy_from_flags(deck, monkeypatch):
    from deckifyr import cli
    from deckifyr.web import app as web_app

    captured = {}

    def fake_create_app(*args, **kwargs):
        captured.update(kwargs)
        return object()

    class FakeServer:
        def __init__(self, config):
            pass

        def run(self):
            pass

    monkeypatch.setattr(web_app, "create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.Server", FakeServer)
    monkeypatch.setattr("uvicorn.Config", lambda *a, **k: None)

    cli.main(
        ["serve", "--project", str(deck), "--quarto-bin", "/q", "--trusted-binaries-only"]
    )

    assert captured["policy"] == TrustPolicy(quarto_bin="/q", trusted_binaries_only=True)
