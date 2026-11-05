"""Build hook for the Python wheel (issue #86). All real metadata is in
pyproject.toml; this exists for one thing setuptools can't express.

`deckifyr init` (no flags) scaffolds a project from the bundled minimal
example. That example is deliberately a single shared fixture at
`inst/examples/minimal-deck/` -- R's `system.file("examples", ...)`, the R
and Python test suites and the web e2e fixture all read it from there -- but
`inst/examples/` sits outside the Python package directory (`inst/python/`),
so a wheel built from `pyproject.toml` alone silently omits it and `init`
fails after `pip install`. Rather than move the fixture (and every
reference to it) or keep a second copy that could drift, copy it into the
*build tree* at wheel-build time, where `cli._examples_dir()` looks first.
The repo and the R package keep using `inst/examples/` directly.
"""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

EXAMPLE_DIR = Path(__file__).resolve().parent / "inst" / "examples" / "minimal-deck"
EXAMPLE_FILES = ("design.yaml", "layouts.yaml", "presentation.yaml")


class build_py_with_examples(build_py):
    def run(self):
        super().run()
        if self.editable_mode:
            # An editable install runs from the checkout, where
            # `_examples_dir()` falls back to `inst/examples/` itself.
            return
        missing = [n for n in EXAMPLE_FILES if not (EXAMPLE_DIR / n).is_file()]
        if missing:
            # Never ship a wheel whose `deckifyr init` is silently broken.
            raise FileNotFoundError(
                f"bundled example project files missing from {EXAMPLE_DIR}: {missing} "
                "(an sdist must include them -- see MANIFEST.in)"
            )
        dest = Path(self.build_lib) / "deckifyr" / "_examples" / "minimal-deck"
        dest.mkdir(parents=True, exist_ok=True)
        for name in EXAMPLE_FILES:
            shutil.copyfile(EXAMPLE_DIR / name, dest / name)


setup(cmdclass={"build_py": build_py_with_examples})
