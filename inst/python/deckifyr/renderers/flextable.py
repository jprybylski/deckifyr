"""Rendering a `.rds` flextable reportifyr artifact to a picture (issue
#57).

In this project's reportifyr/pharma convention, a `.rds` reportifyr
table artifact is a `flextable` object (produced via R's
`format_flextable()`) -- rich formatting (merged cells, per-cell
borders/colors, multi-level headers) that a native PowerPoint table
can't represent. So, the same as a `type: quarto` fragment,
`deckifyr.pptx.compose._add_reportifyr_shape` places it as a picture
rather than attempting a cell-by-cell reconstruction (`.csv`/`.parquet`
reportifyr artifacts stay on the native-table path,
`deckifyr.resolvers.table.TableResolver`).

This module shells out to a real `Rscript` binary to rasterize the
`.rds` object via `flextable::save_as_image()` -- the same "shell out to
an already-trusted external tool, raise `MissingDependencyError` if it's
not on PATH" posture `deckifyr.renderers.quarto`/`deckifyr.renderers
.preview` already establish for Quarto/LibreOffice. Confirmed against a
real `flextable` 0.10.0 install: `save_as_image()`'s PNG output is
genuinely transparent by default (no `bg="transparent"` argument needed,
unlike its own `svg` branch) and needs no headless-browser backend
(`webshot2`/`chromote`) -- only base R graphics -- so `Rscript` + the
`flextable` package is the entire dependency surface. No new Python
dependency: a pure-Python `.rds` reader (e.g. `pyreadr`) would only
recover raw cell data, not flextable's actual rendering instructions.

The actual R source lives in a bundled sibling file,
`render_flextable.R`, invoked with `Rscript --vanilla
render_flextable.R <input.rds> <output.png> <dpi>` -- **list-form
subprocess args, never a string-interpolated/`shell=True` invocation**,
so an artifact path with an unusual character can't affect how the R
script is parsed. The script exits with a **reserved status 2**
specifically when the `flextable` R package itself isn't installed (not
R's own default of 1 for an uncaught `stop()`), so `render_flextable_png`
can raise a distinct `MissingDependencyError` for that case instead of a
generic render-failure message -- mirroring the same "distinguish
'you're missing something' from 'this input caused a real failure'"
split `MissingDependencyError` already draws for Quarto/LibreOffice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from deckifyr.schema.errors import ContentValidationError, MissingDependencyError

_R_INSTALL_URL = "https://cran.r-project.org/"
_FLEXTABLE_INSTALL_URL = "https://cran.r-project.org/package=flextable"
_RENDER_SCRIPT = Path(__file__).resolve().parent / "render_flextable.R"

# The bundled R script's own reserved exit code for "the flextable
# package isn't installed" -- distinct from R's default exit status of
# 1 for any other uncaught `stop()`.
_MISSING_PACKAGE_EXIT_CODE = 2


@dataclass
class FlextableExecutionConfig:
    """Resolved `presentation.yaml` `build.reportifyr.flextable` settings
    (spec section 9.1-adjacent -- flextable rendering only ever exists to
    serve a reportifyr `.rds` artifact, so it's nested under
    `ReportifyrConfig` rather than a `QuartoConfig`/`PreviewConfig`-style
    top-level `BuildConfig` sibling).
    """

    binary: str = "Rscript"
    timeout_seconds: float = 60
    max_output_bytes: int = 5_000_000
    # Maps to `flextable::save_as_image()`'s own `res=` (resolution in
    # DPI) -- 200 matches that function's own default.
    dpi: int = 200


def _require_rscript(config: FlextableExecutionConfig) -> None:
    if shutil.which(config.binary) is None:
        raise MissingDependencyError(
            f"Rscript binary {config.binary!r} was not found on PATH -- "
            f"install R ({_R_INSTALL_URL}) to build a presentation "
            "containing a reportifyr .rds (flextable) artifact, or set "
            "build.reportifyr.flextable.binary to its full path",
            name="rscript",
            display_name="R (Rscript)",
            install_url=_R_INSTALL_URL,
        )


def _check_size(data: bytes, config: FlextableExecutionConfig, *, label: str) -> None:
    if len(data) > config.max_output_bytes:
        raise ContentValidationError(
            f"{label}: flextable render output ({len(data)} bytes) exceeds "
            f"the configured limit of {config.max_output_bytes} bytes "
            "(build.reportifyr.flextable.max_output_bytes)"
        )


def render_flextable_png(rds_path: Path, *, config: FlextableExecutionConfig) -> Path:
    """Render `rds_path` (a `saveRDS()`-serialized `flextable` object) to
    a standalone temp PNG. Returns a path the caller owns and must
    delete once done with it -- same contract
    `deckifyr.renderers.quarto.render_image` documents for its own
    returned image path.
    """
    _require_rscript(config)

    fd, out_name = tempfile.mkstemp(prefix="deckifyr-flextable-", suffix=".png")
    os.close(fd)
    out_path = Path(out_name)

    cmd = [
        config.binary,
        "--vanilla",
        str(_RENDER_SCRIPT),
        str(rds_path),
        str(out_path),
        str(config.dpi),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=rds_path.parent,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        out_path.unlink(missing_ok=True)
        raise ContentValidationError(
            f"{rds_path}: flextable render exceeded its "
            f"{config.timeout_seconds}s execution timeout "
            "(build.reportifyr.flextable.timeout_seconds)"
        ) from exc

    if result.returncode == _MISSING_PACKAGE_EXIT_CODE:
        out_path.unlink(missing_ok=True)
        raise MissingDependencyError(
            f"{rds_path}: the R 'flextable' package is required to render "
            f"reportifyr .rds table artifacts ({_FLEXTABLE_INSTALL_URL})",
            name="flextable",
            display_name="R package 'flextable'",
            install_url=_FLEXTABLE_INSTALL_URL,
        )
    if result.returncode != 0:
        out_path.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout).strip()
        raise ContentValidationError(f"{rds_path}: flextable render failed:\n{detail}")
    if not out_path.is_file():
        raise ContentValidationError(
            f"{rds_path}: flextable render did not produce the expected "
            "PNG output"
        )

    _check_size(out_path.read_bytes(), config, label=str(rds_path))
    return out_path
