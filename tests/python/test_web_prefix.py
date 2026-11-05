"""`deckifyr serve` behind a reverse proxy mounted under a path prefix (issue #82).

These tests run a *real* uvicorn server (not `TestClient`) and a minimal
prefix-aware proxy in front of it, because the failure this guards against
-- the built frontend emitting root-relative `/assets/...` / `/api/...`
URLs that escape the prefix -- only shows up when something other than the
app itself owns the URL space. The proxy answers 404 for anything outside
its mount prefix, which is exactly what a real launcher origin does to a
request that escapes it.
"""

from __future__ import annotations

import http.client
import io
import json
import pathlib
import re
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin

import pytest
from pptx import Presentation

uvicorn = pytest.importorskip("uvicorn")

from deckifyr.web.app import create_app, strip_path_prefix  # noqa: E402
from deckifyr.web.security import build_host_policy  # noqa: E402

PREFIX = "/apps/deckifyr"
STATIC_DIR = pathlib.Path(__file__).resolve().parents[2] / "inst/python/deckifyr/web/static"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Upstream:
    """A real uvicorn server running `app` on a background thread."""

    def __init__(self, app, port: int | None = None) -> None:
        self.port = port or _free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Upstream:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert self.server.started, "uvicorn did not start"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _make_proxy_handler(
    upstream_port: int, *, strip_prefix: bool, extra_headers: dict[str, str] | None = None
):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # silence test output
            pass

        def _proxy(self) -> None:
            if not (self.path == PREFIX or self.path.startswith(PREFIX + "/")):
                # Anything outside the mount prefix is not ours -- this is
                # what makes a root-relative URL fail loudly in these tests.
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            path = self.path[len(PREFIX) :] or "/" if strip_prefix else self.path
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            conn = http.client.HTTPConnection("127.0.0.1", upstream_port, timeout=30)
            headers = {
                k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")
            }
            # A real launcher injects its per-launch secret here (issue #88); the
            # browser never holds it. Replaces any same-named client header so a
            # page cannot supply its own.
            for key in list(headers):
                if key.lower() in {k.lower() for k in (extra_headers or {})}:
                    del headers[key]
            headers.update(extra_headers or {})
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ("transfer-encoding", "connection", "content-length"):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _proxy

    return Handler


class _Proxy:
    def __init__(
        self,
        upstream_port: int,
        *,
        strip_prefix: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _make_proxy_handler(
                upstream_port, strip_prefix=strip_prefix, extra_headers=extra_headers
            ),
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _Proxy:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def request(self, method: str, path: str, payload=None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def json(self, method: str, path: str, payload=None):
        status, data = self.request(method, path, payload)
        return status, json.loads(data) if data else None


@pytest.fixture
def project_dir(minimal_deck_dir, tmp_path) -> pathlib.Path:
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, tmp_path / name)
    return tmp_path


@pytest.fixture(params=["strip", "root-path"])
def proxied(request, project_dir) -> Iterator[_Proxy]:
    """The editor behind a proxy at `PREFIX`, in both supported modes.

    `strip`: the proxy removes the prefix (the default, documented mode --
    the app needs no configuration). `root-path`: the proxy forwards the
    prefix untouched and the app is wrapped the way `--root-path` wraps it.
    """
    strip = request.param == "strip"
    app = create_app(project_dir)
    if not strip:
        app = strip_path_prefix(app, PREFIX)
    with _Upstream(app) as upstream:
        with _Proxy(upstream.port, strip_prefix=strip) as proxy:
            yield proxy


def test_index_and_every_asset_load_through_the_prefix(proxied):
    status, html = proxied.request("GET", f"{PREFIX}/")
    assert status == 200
    text = html.decode()
    assert "<title>deckifyr</title>" in text

    refs = re.findall(r'(?:src|href)="([^"]+)"', text)
    local_refs = [r for r in refs if not r.startswith(("http:", "https:", "data:"))]
    assert any("assets/" in r for r in local_refs), local_refs
    assert "logo.png" in local_refs
    for ref in local_refs:
        # Resolve exactly as a browser would from the page URL.
        resolved = urljoin(f"{PREFIX}/", ref)
        assert resolved.startswith(f"{PREFIX}/"), f"{ref!r} escapes the prefix -> {resolved}"
        asset_status, body = proxied.request("GET", resolved)
        assert asset_status == 200, resolved
        assert body


def test_paths_outside_the_prefix_do_not_reach_the_app(proxied):
    status, _ = proxied.request("GET", "/api/health")
    assert status == 404


def test_project_config_edit_save_and_build_work_through_the_prefix(proxied, project_dir):
    api = f"{PREFIX}/api"

    status, health = proxied.json("GET", f"{api}/health")
    assert status == 200 and health["status"] == "ok"

    status, project = proxied.json("GET", f"{api}/project")
    assert status == 200 and project

    status, presentation = proxied.json("GET", f"{api}/config/presentation")
    assert status == 200
    presentation["metadata"]["title"] = "Edited behind a prefix"
    status, _ = proxied.json("PUT", f"{api}/config/presentation", presentation)
    assert status == 200
    status, _ = proxied.json("POST", f"{api}/save")
    assert status == 200
    assert "Edited behind a prefix" in (project_dir / "presentation.yaml").read_text()

    status, job = proxied.json("POST", f"{api}/build")
    assert status == 200
    job_id = job["job_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, body = proxied.json("GET", f"{api}/jobs/{job_id}")
        assert status == 200
        if body["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.25)
    assert body["status"] == "succeeded", body

    # The artifact URL a browser follows is page-relative (`jobArtifactUrl`);
    # fetch it the way the prefixed page would.
    status, data = proxied.request("GET", f"{api}/jobs/{job_id}/artifacts/pptx")
    assert status == 200
    Presentation(io.BytesIO(data))


def test_built_bundle_has_no_root_relative_api_or_asset_urls():
    """Issue #82's CI-greppable guarantee on the committed bundle."""
    offenders = []
    for path in [STATIC_DIR / "index.html", *sorted((STATIC_DIR / "assets").glob("*.js"))]:
        text = path.read_text(encoding="utf-8")
        for needle in ('"/api/', "`/api/", "'/api/", '"/assets/', '"/logo.png'):
            if needle in text:
                offenders.append((path.name, needle))
    assert not offenders, offenders


# --- a guarded editor behind a header-injecting proxy (issue #88) --------------

TOKEN = "per-launch-secret"


@pytest.fixture(params=["strip", "root-path"])
def guarded(request, project_dir) -> Iterator[tuple[_Proxy, _Upstream, str]]:
    """The editor with a Host allow-list and a required API token, behind a
    proxy that injects that token -- the workspace-launcher arrangement.

    Yields `(proxy, upstream, mount)`: `mount` is the path prefix the *upstream*
    itself serves under ("" when the proxy strips it, `PREFIX` under `--root-path`)."""
    strip = request.param == "strip"
    port = _free_port()
    app = create_app(
        project_dir, host_policy=build_host_policy(port, "127.0.0.1"), api_token=TOKEN
    )
    if not strip:
        app = strip_path_prefix(app, PREFIX)
    with _Upstream(app, port=port) as upstream:
        with _Proxy(
            upstream.port, strip_prefix=strip, extra_headers={"X-Deckifyr-Api-Token": TOKEN}
        ) as proxy:
            yield proxy, upstream, ("" if strip else PREFIX)


def _direct(upstream: _Upstream, method: str, path: str, headers=None) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", upstream.port, timeout=30)
    conn.request(method, path, headers=headers or {})
    status = conn.getresponse().status
    conn.close()
    return status


def test_the_whole_editor_works_through_a_token_injecting_proxy(guarded):
    proxy, _, _ = guarded
    api = f"{PREFIX}/api"

    status, html = proxy.request("GET", f"{PREFIX}/")
    assert status == 200 and b"<title>deckifyr</title>" in html
    assert proxy.json("GET", f"{api}/health")[0] == 200
    assert proxy.json("GET", f"{api}/project")[0] == 200
    status, presentation = proxy.json("GET", f"{api}/config/presentation")
    assert status == 200
    assert proxy.json("PUT", f"{api}/config/presentation", presentation)[0] == 200
    assert proxy.json("POST", f"{api}/save")[0] == 200
    status, job = proxy.json("POST", f"{api}/build")
    assert status == 200 and job["job_id"]


def test_the_loopback_port_is_not_usable_without_the_token(guarded):
    # The proxy cannot protect a port a page can reach directly; the token can.
    _, upstream, mount = guarded
    api = f"{mount}/api"
    assert _direct(upstream, "GET", f"{api}/health") == 200  # health stays open
    assert _direct(upstream, "GET", f"{api}/project") == 403
    assert _direct(upstream, "POST", f"{api}/build") == 403
    assert _direct(upstream, "POST", f"{api}/shutdown") == 403
    assert _direct(upstream, "GET", f"{api}/project", {"X-Deckifyr-Api-Token": TOKEN}) == 200
    assert _direct(upstream, "GET", f"{mount}/") == 200  # static assets stay open


def test_a_double_prefixed_path_cannot_skip_the_token_under_root_path(guarded):
    # Under --root-path the app is wrapped by `strip_path_prefix`, and Starlette
    # strips `root_path` once more when routing, so `/p/p/api/...` reaches an API
    # route. The token check must see that, not just the raw path.
    _, upstream, mount = guarded
    if not mount:
        pytest.skip("only meaningful when the app itself is mounted under a prefix")
    double = f"{mount}{mount}/api/project"
    assert _direct(upstream, "GET", double) == 403
    assert _direct(upstream, "GET", double, {"X-Deckifyr-Api-Token": TOKEN}) == 200
