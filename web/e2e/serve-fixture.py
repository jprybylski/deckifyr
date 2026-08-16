#!/usr/bin/env python3
"""Copies `inst/examples/minimal-deck` into a fresh scratch directory and
execs `deckifyr serve` against the copy.

`playwright.config.ts`'s own `webServer.command` runs this rather than
serving the tracked fixture directly, because these e2e tests are
real UI interactions -- they PATCH/PUT/discard against whatever project
is bound, the same way `deckifyr serve` always works (spec section 12).
Pointing at the tracked `inst/examples/minimal-deck` would mean every
e2e run leaves that shared fixture's `presentation.yaml` mutated (or
worse, differently mutated depending on which test ran last) -- the same
"toggled the tracked demo-deck example's watermark off via a live
deck_serve() session" trap CONTRIBUTING.md's own screenshot-regeneration
recipe already warns about for a manual Playwright session against
`examples/demo-deck`.

`minimal-deck` (not `examples/demo-deck`) is the fixture on purpose:
it's the one this repo already treats as the canonical, dependency-free
test fixture (`tests/python/`, `tests/testthat/`, and `deckifyr init`
all use it), and its `title` slide's `deck-title` markdown element is
enough to exercise the drag/select/discard flow these tests care about
without needing the external `quarto`/reportifyr toolchain `demo-deck`
pulls in.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "inst" / "examples" / "minimal-deck"
PORT = os.environ.get("DECKIFYR_E2E_PORT", "8399")


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="deckifyr-e2e-"))
    shutil.copytree(FIXTURE_DIR, scratch, dirs_exist_ok=True)

    os.chdir(REPO_ROOT)
    os.execvp(
        "uv",
        [
            "uv",
            "run",
            "--extra",
            "dev",
            "deckifyr",
            "serve",
            "--project",
            str(scratch),
            "--port",
            PORT,
        ],
    )


if __name__ == "__main__":
    main()
