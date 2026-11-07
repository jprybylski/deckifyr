"""Offline mode (issue #93): nothing reaches the network unless asked for.

On when `DECKIFYR_OFFLINE` or uv's own `UV_OFFLINE` is truthy. The R
wrappers set both when `options(deckifyr.offline = TRUE)`, so the CLI
gives a user of either facade the same behaviour. The only network use
inside the Python engine is `init --from-repo` (`git clone`); the rest of
offline mode -- `uv run --no-sync`, no index, no Python downloads -- is the
launcher's job (`R/offline.R`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

OFFLINE_ENV_VARS = ("DECKIFYR_OFFLINE", "UV_OFFLINE")
_TRUTHY = {"1", "true", "yes", "on"}


def offline_mode(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return any((env.get(name) or "").strip().lower() in _TRUTHY for name in OFFLINE_ENV_VARS)


def offline_from_repo_message(clone_url: str | None = None) -> str:
    target = f" ({clone_url})" if clone_url else ""
    return (
        f"cannot fetch a template repository{target} in offline mode "
        "(DECKIFYR_OFFLINE/UV_OFFLINE is set) -- it needs a git clone over the "
        "network. Clone it while you have access and pass the checkout with "
        "--from-dir instead"
    )
