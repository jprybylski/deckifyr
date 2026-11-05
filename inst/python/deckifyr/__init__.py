"""deckifyr: a declarative, code-first PowerPoint compiler.

This package is the canonical engine described in
`deckifyr-specification.md` at the repository root: it is bundled
unmodified inside the R package under `inst/python/` (spec section 5.3)
and is also the source directory for the standalone Python wheel/CLI --
never fork or duplicate this tree for one facade or the other.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # The installed distribution's version, which pyproject.toml reads from
    # the repo-root VERSION file -- so a wheel, a manifest's
    # `deckifyr_version` and the release tag all agree.
    __version__ = version("deckifyr")
except PackageNotFoundError:  # pragma: no cover
    # Running from a bare source tree with no installed metadata -- notably
    # the R package, which puts inst/python on the path via pyro rather than
    # pip-installing it.
    __version__ = "0.0.0.dev0"
