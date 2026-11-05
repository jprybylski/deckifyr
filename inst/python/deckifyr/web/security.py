"""Request guard for `deckifyr serve` (issue #88).

`serve` binds a loopback port, and any page the user has open in *any* tab can
reach that port. Three independent defences, installed as one pure-ASGI
middleware inside `create_app` (so it runs after `strip_path_prefix` and sees
the real `Host` header and the routed path):

1. **Host allow-list** -- DNS rebinding turns a remote page into a same-origin
   one for `127.0.0.1`, giving it the whole API. Only the loopback names on the
   served port, the `--host` it bound, and any `--allowed-host` are accepted;
   anything else gets `421`.
2. **Cross-site rejection** -- for state-changing methods, `403` when
   `Sec-Fetch-Site` says the request did not come from this origin
   (`cross-site`, and also `same-site`: another local dev server on a sibling
   port is exactly the kind of page this is meant to stop), or when an
   `Origin` header's authority is not allowed. A cross-site "simple" POST needs
   no CORS preflight, so without this the body-less routes (`/api/build`,
   `/api/discard`, `/api/shutdown`, ...) were drivable by any website. Requests
   carrying neither header (curl, the R facade, CI) are not browsers and pass;
   `same-origin`/`none` (the editor itself, the R Viewer pane) pass.
3. **Optional launcher token** (`--api-token-env VAR`) -- when set, every
   `/api/*` request except `GET /api/health` must carry
   `X-Deckifyr-Api-Token`, compared in constant time. A supervising proxy
   injects it; the browser bundle never sees it. Static assets stay open.

It is a middleware rather than per-route code so no route (present or future)
can forget it, and it answers in the app's own `{code, message}` shape.

The token guard decides "is this an API request?" from *both* the raw path and
the path Starlette will actually route (it strips `root_path`), because those
can differ: behind `--root-path`, `/apps/x/apps/x/api/build` is stripped once by
`strip_path_prefix` and then routed as `/api/build` -- a check on the raw path
alone would have waved it through unauthenticated.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

TOKEN_HEADER = "x-deckifyr-api-token"

HOST_NOT_ALLOWED = "E_HOST_NOT_ALLOWED"
CROSS_SITE_REJECTED = "E_CROSS_SITE_REJECTED"
API_TOKEN_REQUIRED = "E_API_TOKEN_REQUIRED"

_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# What a browser calls "this origin" (or a user-typed navigation).
_SAME_ORIGIN_FETCH_SITES = {"same-origin", "none"}


def split_authority(authority: str) -> tuple[str, int | None]:
    """`host[:port]` -> (lowercased host without brackets/trailing dot, port|None).

    Handles `[::1]:8000`. A malformed port yields `-1` so it can never equal a
    real one.
    """
    authority = authority.strip().lower()
    if authority.startswith("["):
        end = authority.find("]")
        if end == -1:
            return authority, -1
        host, rest = authority[1:end], authority[end + 1 :]
        port_text = rest[1:] if rest.startswith(":") else ""
    elif authority.count(":") == 1:
        host, _, port_text = authority.partition(":")
    else:
        host, port_text = authority, ""
    host = host.rstrip(".")
    if not port_text:
        return host, None
    return host, int(port_text) if port_text.isdigit() else -1


class HostPolicy:
    """Which `Host`/`Origin` authorities are acceptable.

    The loopback names (and the bound `--host` unless it is a wildcard) are
    accepted only on the served `port`. An `--allowed-host` without a port
    (the usual case for a proxy's public name) matches any port, because the
    proxy's own port is not ours to know; one with a port must match it.
    """

    def __init__(self, port: int | None, extra: Iterable[str] = (), bound_host: str | None = None):
        self._port = port
        self._builtin = set(_LOOPBACK_NAMES)
        if bound_host is not None and bound_host.strip().lower() not in _WILDCARD_HOSTS:
            self._builtin.add(split_authority(bound_host)[0])
        self._extra: list[tuple[str, int | None]] = [split_authority(e) for e in extra if e.strip()]

    def allows(self, authority: str | None) -> bool:
        if not authority:
            return False
        host, port = split_authority(authority)
        if host in self._builtin and (self._port is None or port == self._port):
            return True
        return any(host == h and (p is None or p == port) for h, p in self._extra)

    def describe(self) -> str:
        names = sorted(self._builtin) + [h if p is None else f"{h}:{p}" for h, p in self._extra]
        return ", ".join(names)


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    # ASGI header names are lowercased bytes; a repeated header keeps its first value.
    out: dict[str, str] = {}
    for key, value in scope.get("headers", []):
        out.setdefault(key.decode("latin-1"), value.decode("latin-1"))
    return out


def _route_path(scope: dict[str, Any]) -> str:
    """The path Starlette will route: `path` minus `root_path` when it starts with it."""
    path = scope.get("path", "")
    root = scope.get("root_path", "")
    if root and path.startswith(root):
        rest = path[len(root) :]
        if rest == "" or rest.startswith("/"):
            return rest or "/"
    return path


def _looks_like_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class RequestGuard:
    def __init__(
        self,
        app: Any,
        *,
        host_policy: HostPolicy | None = None,
        api_token: str | None = None,
    ) -> None:
        self.app = app
        self.host_policy = host_policy
        self.api_token = api_token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rejection = self._check(scope)
        if rejection is not None:
            status, code, message = rejection
            await JSONResponse({"code": code, "message": message}, status_code=status)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)

    def _check(self, scope: dict[str, Any]) -> tuple[int, str, str] | None:
        headers = _headers(scope)
        method = scope.get("method", "GET").upper()

        if self.host_policy is not None and not self.host_policy.allows(headers.get("host")):
            return (
                421,
                HOST_NOT_ALLOWED,
                f"Host {headers.get('host', '')!r} is not allowed for this server "
                f"(allowed: {self.host_policy.describe()}); use --allowed-host to add a "
                "proxy's name",
            )

        if method not in _SAFE_METHODS:
            fetch_site = headers.get("sec-fetch-site", "").lower()
            if fetch_site and fetch_site not in _SAME_ORIGIN_FETCH_SITES:
                return (
                    403,
                    CROSS_SITE_REJECTED,
                    f"cross-site request rejected (Sec-Fetch-Site: {fetch_site})",
                )
            origin = headers.get("origin")
            if origin is not None and self.host_policy is not None:
                authority = urlsplit(origin).netloc if origin != "null" else ""
                if not self.host_policy.allows(authority):
                    return (
                        403,
                        CROSS_SITE_REJECTED,
                        f"request from origin {origin!r} rejected; it is not an allowed origin",
                    )

        if self.api_token is not None:
            raw_path = scope.get("path", "")
            route_path = _route_path(scope)
            is_api = _looks_like_api(raw_path) or _looks_like_api(route_path)
            is_health = (
                method in {"GET", "HEAD"}
                and raw_path == "/api/health"
                and route_path == "/api/health"
            )
            if is_api and not is_health:
                supplied = headers.get(TOKEN_HEADER, "")
                if not hmac.compare_digest(supplied.encode(), self.api_token.encode()):
                    return (
                        403,
                        API_TOKEN_REQUIRED,
                        f"missing or invalid {TOKEN_HEADER.title()} header",
                    )
        return None


def build_host_policy(
    port: int | None, bound_host: str | None, allowed_hosts: Sequence[str] = ()
) -> HostPolicy:
    return HostPolicy(port, allowed_hosts, bound_host)
