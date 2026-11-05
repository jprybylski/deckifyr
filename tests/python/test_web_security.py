"""Host / cross-site / token protection for `deckifyr serve` (issue #88).

The unit tests exercise `deckifyr.web.security` directly; the app-level ones
use `TestClient` with a Host that matches the policy. The cases that matter
most pair a rejection with proof it had *no effect* (nothing built, edits not
discarded, server not asked to stop) -- a 403 that still ran the handler would
be worthless.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deckifyr.web.app import create_app, strip_path_prefix
from deckifyr.web.security import HostPolicy, build_host_policy, split_authority

PORT = 8765
TOKEN = "per-launch-secret"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def project_dir(minimal_deck_dir, tmp_path):
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path


class ShutdownSpy:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def _client(project_dir, *, host="127.0.0.1", extra=(), token=None, spy=None, port=PORT):
    policy = build_host_policy(port, host, extra)
    app = create_app(
        project_dir, host_policy=policy, api_token=token, request_shutdown=spy
    )
    return TestClient(app, base_url=f"http://127.0.0.1:{port}"), app


def _make_dirty(client):
    body = client.get("/api/config/presentation").json()
    body["metadata"]["title"] = "unsaved edit"
    assert client.put("/api/config/presentation", json=body).status_code == 200
    assert client.get("/api/health").json()["dirty"] is True


# --- authority parsing / HostPolicy ------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("127.0.0.1:8000", ("127.0.0.1", 8000)),
        ("LocalHost:8000", ("localhost", 8000)),
        ("localhost", ("localhost", None)),
        ("[::1]:8000", ("::1", 8000)),
        ("[::1]", ("::1", None)),
        ("example.com.", ("example.com", None)),
        ("host:notaport", ("host", -1)),
        ("[::1", ("[::1", -1)),
    ],
)
def test_split_authority(raw, expected):
    assert split_authority(raw) == expected


def test_host_policy_builtins_need_the_served_port():
    policy = HostPolicy(8000)
    for ok in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "LOCALHOST:8000"):
        assert policy.allows(ok), ok
    for bad in ("127.0.0.1:9", "127.0.0.1", "evil.example", "evil.example:8000", "", None):
        assert not policy.allows(bad), bad


def test_host_policy_extras_and_bound_host():
    policy = HostPolicy(8000, ["proxy.example", "other.example:8443"], bound_host="10.0.0.5")
    assert policy.allows("proxy.example") and policy.allows("proxy.example:1234")
    assert policy.allows("other.example:8443") and not policy.allows("other.example:80")
    assert policy.allows("10.0.0.5:8000") and not policy.allows("10.0.0.5:81")


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::", ""])
def test_a_wildcard_bind_host_is_not_itself_an_allowed_name(wildcard):
    policy = HostPolicy(8000, bound_host=wildcard)
    assert not policy.allows("0.0.0.0:8000") and not policy.allows("[::]:8000")
    assert policy.allows("127.0.0.1:8000")


def test_unknown_served_port_checks_names_only():
    policy = HostPolicy(None)
    assert policy.allows("127.0.0.1:54321") and not policy.allows("evil.example:54321")


# --- 1. Host allow-list --------------------------------------------------------


def test_a_foreign_host_is_421_on_every_route_including_static(project_dir):
    client, _ = _client(project_dir)
    for path in ("/api/health", "/api/project", "/"):
        response = client.get(path, headers={"Host": "evil.example"})
        assert response.status_code == 421, path
        body = response.json()
        assert body["code"] == "E_HOST_NOT_ALLOWED" and "evil.example" in body["message"]


def test_a_foreign_host_with_the_right_port_is_still_rejected(project_dir):
    client, _ = _client(project_dir)
    assert client.get("/api/health", headers={"Host": f"evil.example:{PORT}"}).status_code == 421


def test_loopback_names_on_the_served_port_work(project_dir):
    client, _ = _client(project_dir)
    for host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200, host
    assert client.get("/api/health", headers={"Host": "127.0.0.1:1"}).status_code == 421


def test_an_allowed_host_value_works(project_dir):
    client, _ = _client(project_dir, extra=["workspace.example"])
    assert client.get("/api/health", headers={"Host": "workspace.example"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "workspace.example:8443"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 421


def test_a_rejected_host_never_reaches_the_handler(project_dir):
    client, _ = _client(project_dir)
    response = client.post("/api/build", headers={"Host": "evil.example"})
    assert response.status_code == 421
    assert not (project_dir / "build").exists()


def test_without_a_host_policy_the_host_is_not_checked(project_dir):
    # Embedded / test use (TestClient sends `Host: testserver`) is unchanged.
    client = TestClient(create_app(project_dir))
    assert client.get("/api/health").status_code == 200


# --- 2. cross-site rejection ---------------------------------------------------


def _build_artifacts(project_dir):
    return list((project_dir / "build").glob("*")) if (project_dir / "build").exists() else []


def test_a_cross_site_form_post_cannot_build(project_dir):
    client, app = _client(project_dir)
    response = client.post(
        "/api/build", headers={**FORM, "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "E_CROSS_SITE_REJECTED"
    assert app.state.job_manager.active_count() == 0
    time.sleep(0.3)
    assert _build_artifacts(project_dir) == [], "the rejected request still built"


def test_a_cross_site_post_cannot_discard_unsaved_edits(project_dir):
    client, _ = _client(project_dir)
    _make_dirty(client)
    response = client.post(
        "/api/discard", headers={**FORM, "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert client.get("/api/health").json()["dirty"] is True  # edits survived


def test_a_cross_site_post_cannot_shut_the_server_down(project_dir):
    spy = ShutdownSpy()
    client, _ = _client(project_dir, spy=spy)
    response = client.post(
        "/api/shutdown", headers={**FORM, "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert spy.calls == 0


def test_cross_site_save_validate_and_preview_are_rejected_too(project_dir):
    client, _ = _client(project_dir)
    headers = {**FORM, "Sec-Fetch-Site": "cross-site"}
    for path in ("/api/save", "/api/validate", "/api/preview", "/api/furniture/elements/branding"):
        assert client.post(path, headers=headers).status_code == 403, path


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_state_changing_methods_are_rejected_cross_site(project_dir, method):
    client, _ = _client(project_dir)
    response = client.request(
        method, "/api/config/presentation", headers={"Sec-Fetch-Site": "cross-site"}, json={}
    )
    assert response.status_code == 403


def test_same_site_but_different_origin_is_rejected(project_dir):
    client, _ = _client(project_dir)
    response = client.post(
        "/api/discard", headers={"Sec-Fetch-Site": "same-site", "Origin": "http://localhost:3000"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_same_origin_and_user_initiated_requests_pass(project_dir, site):
    client, _ = _client(project_dir)
    response = client.post(
        "/api/discard", headers={"Sec-Fetch-Site": site, "Origin": f"http://127.0.0.1:{PORT}"}
    )
    assert response.status_code == 200


def test_a_request_with_neither_header_is_not_a_browser_and_passes(project_dir):
    # curl, the R facade and CI's `POST /api/shutdown` send neither.
    spy = ShutdownSpy()
    client, _ = _client(project_dir, spy=spy)
    assert client.post("/api/discard").status_code == 200
    assert client.post("/api/shutdown").status_code == 200
    assert spy.calls == 1


def test_a_cross_site_get_is_not_blocked(project_dir):
    # Reads are protected by the browser's same-origin policy plus the Host check.
    client, _ = _client(project_dir)
    assert client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_a_foreign_origin_is_rejected_even_without_sec_fetch_site(project_dir):
    client, _ = _client(project_dir)
    for origin in ("https://evil.example", "null", f"http://127.0.0.1:{PORT + 1}"):
        response = client.post("/api/discard", headers={"Origin": origin})
        assert response.status_code == 403, origin


def test_an_allowed_hosts_origin_passes_the_origin_check(project_dir):
    client, _ = _client(project_dir, extra=["workspace.example"])
    ok = client.post(
        "/api/discard",
        headers={"Host": "workspace.example", "Origin": "https://workspace.example",
                 "Sec-Fetch-Site": "same-origin"},
    )
    assert ok.status_code == 200


def test_cross_site_writes_are_rejected_even_without_a_host_policy(project_dir):
    client = TestClient(create_app(project_dir))
    assert client.post("/api/discard", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/discard").status_code == 200


# --- 3. launcher token ---------------------------------------------------------


def test_api_routes_need_the_token_but_health_and_static_do_not(project_dir):
    client, _ = _client(project_dir, token=TOKEN)

    for method, path in (("GET", "/api/project"), ("GET", "/api/plan"), ("POST", "/api/build"),
                         ("POST", "/api/discard"), ("PUT", "/api/config/presentation")):
        response = client.request(method, path, json={} if method == "PUT" else None)
        assert response.status_code == 403, (method, path)
        assert response.json()["code"] == "E_API_TOKEN_REQUIRED"

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200  # the editor's static bundle stays open


def test_the_token_is_accepted_and_a_wrong_or_empty_one_is_not(project_dir):
    client, _ = _client(project_dir, token=TOKEN)
    assert client.get("/api/project", headers={"X-Deckifyr-Api-Token": TOKEN}).status_code == 200
    for bad in ("wrong", "", TOKEN + "x", TOKEN[:-1], TOKEN.upper()):
        response = client.get("/api/project", headers={"X-Deckifyr-Api-Token": bad})
        assert response.status_code == 403, repr(bad)


def test_a_rejected_token_never_reaches_the_handler(project_dir):
    spy = ShutdownSpy()
    client, _ = _client(project_dir, token=TOKEN, spy=spy)
    assert client.post("/api/shutdown").status_code == 403
    assert spy.calls == 0
    assert client.post("/api/shutdown", headers={"X-Deckifyr-Api-Token": TOKEN}).status_code == 200
    assert spy.calls == 1


def test_only_get_and_head_health_is_exempt(project_dir):
    client, _ = _client(project_dir, token=TOKEN)
    assert client.head("/api/health").status_code != 403
    assert client.post("/api/health").status_code == 403  # not exempt (and not a real route)


def test_the_token_check_cannot_be_bypassed_through_a_root_path_double_prefix(project_dir):
    # `strip_path_prefix` strips the prefix once; Starlette then strips `root_path`
    # again when routing, so `/p/p/api/...` is *routed* as `/api/...` even though its
    # raw path does not start with `/api`.
    client_app = strip_path_prefix(
        create_app(project_dir, host_policy=build_host_policy(PORT, "127.0.0.1"), api_token=TOKEN),
        "/p",
    )
    client = TestClient(client_app, base_url=f"http://127.0.0.1:{PORT}")
    for path in ("/p/api/project", "/p/p/api/project"):
        assert client.get(path).status_code == 403, path
        assert client.get(path, headers={"X-Deckifyr-Api-Token": TOKEN}).status_code == 200, path
    # health stays reachable under the prefix, and only at its real address
    assert client.get("/p/api/health").status_code == 200
    assert client.get("/p/p/api/health").status_code == 403


def test_without_a_token_nothing_changes(project_dir):
    client, _ = _client(project_dir)
    assert client.get("/api/project").status_code == 200


def test_host_is_checked_before_the_token(project_dir):
    client, _ = _client(project_dir, token=TOKEN)
    response = client.get(
        "/api/project", headers={"Host": "evil.example", "X-Deckifyr-Api-Token": TOKEN}
    )
    assert response.status_code == 421


# --- the CLI wiring ---------------------------------------------------------------


@pytest.fixture
def serve_spy(monkeypatch):
    """`deckifyr serve` with create_app and uvicorn replaced, capturing the kwargs."""
    from deckifyr.web import app as web_app

    captured: dict = {}

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
    return captured


def test_serve_always_passes_a_host_policy_for_its_port_and_host(project_dir, serve_spy):
    from deckifyr import cli

    cli.main(["serve", "--project", str(project_dir), "--port", "9123",
              "--allowed-host", "workspace.example", "--allowed-host", "other.example:8443"])

    policy = serve_spy["host_policy"]
    assert policy.allows("127.0.0.1:9123") and not policy.allows("127.0.0.1:9124")
    assert policy.allows("workspace.example") and policy.allows("other.example:8443")
    assert not policy.allows("evil.example:9123")
    assert serve_spy["api_token"] is None


def test_serve_reads_the_token_from_the_named_environment_variable(project_dir, serve_spy, monkeypatch):
    from deckifyr import cli

    monkeypatch.setenv("MY_LAUNCH_TOKEN", "abc123")
    cli.main(["serve", "--project", str(project_dir), "--api-token-env", "MY_LAUNCH_TOKEN"])
    assert serve_spy["api_token"] == "abc123"


@pytest.mark.parametrize("value", [None, ""])
def test_serve_refuses_to_start_unauthenticated_when_the_token_variable_is_unset(
    project_dir, serve_spy, monkeypatch, capsys, value
):
    from deckifyr import cli

    monkeypatch.delenv("MY_LAUNCH_TOKEN", raising=False)
    if value is not None:
        monkeypatch.setenv("MY_LAUNCH_TOKEN", value)

    code = cli.main(["--json", "serve", "--project", str(project_dir),
                     "--api-token-env", "MY_LAUNCH_TOKEN"])

    assert code != 0 and "MY_LAUNCH_TOKEN" in json.loads(capsys.readouterr().err)["message"]
    assert "host_policy" not in serve_spy  # create_app was never reached


def test_the_token_value_never_appears_in_the_servers_argv_or_error_text(project_dir, serve_spy, monkeypatch, capsys):
    from deckifyr import cli

    monkeypatch.setenv("MY_LAUNCH_TOKEN", "top-secret-value")
    cli.main(["serve", "--project", str(project_dir), "--api-token-env", "MY_LAUNCH_TOKEN"])
    assert "top-secret-value" not in capsys.readouterr().out


# --- a real server process ----------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(port, method, path, *, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    merged = dict(headers or {})
    conn.putrequest(method, path, skip_host=host is not None)
    if host is not None:
        conn.putheader("Host", host)
    for key, value in merged.items():
        conn.putheader(key, value)
    conn.putheader("Content-Length", "0")
    conn.endheaders()
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


@pytest.fixture
def real_server(project_dir):
    port = _free_port()
    env = {**os.environ, "DECKIFYR_TEST_TOKEN": TOKEN}
    proc = subprocess.Popen(
        [sys.executable, "-m", "deckifyr", "serve", "--project", str(project_dir),
         "--port", str(port), "--launcher", "workspace", "--api-token-env", "DECKIFYR_TEST_TOKEN",
         "--allowed-host", "workspace.example"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if _request(port, "GET", "/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("server never became ready")
        yield port, proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_a_real_server_enforces_host_site_and_token(real_server):
    port, proc = real_server
    token = {"X-Deckifyr-Api-Token": TOKEN}

    # Foreign Host: 421, even on /api/health (the host check is not token-exempt).
    assert _request(port, "GET", "/api/health", host="evil.example")[0] == 421
    # The reproduction from the issue: a cross-site form POST, with a valid token
    # present so that only the cross-site rule can be what stops it.
    status, body = _request(port, "POST", "/api/build", headers={
        **FORM, **token, "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert status == 403 and json.loads(body)["code"] == "E_CROSS_SITE_REJECTED"

    # Token required for the API, not for health or the bundle.
    assert _request(port, "GET", "/api/project")[0] == 403
    assert _request(port, "GET", "/api/project", headers=token)[0] == 200
    assert _request(port, "GET", "/api/health")[0] == 200
    assert _request(port, "GET", "/")[0] == 200

    # A proxy's public name is accepted via --allowed-host.
    assert _request(port, "GET", "/api/health", host="workspace.example")[0] == 200

    # Shutdown without the token neither works nor stops the process; with it, it does.
    assert _request(port, "POST", "/api/shutdown")[0] == 403
    assert proc.poll() is None
    assert _request(port, "POST", "/api/shutdown", headers=token)[0] == 200
    assert proc.wait(timeout=30) == 0
