"""Tests for `deckifyr.renderers.flextable` (issue #57).

`render_flextable_png` shells out to a real `Rscript` binary (and, for a
real render, the R `flextable` package), so real-execution tests skip
cleanly when either is unavailable -- mirroring
`tests/python/test_renderers_quarto.py`'s own `requires_quarto`/
`requires_r` skip pattern (see CLAUDE.md): this is expected local/CI
behavior, not a gap to work around with mocking.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from deckifyr.renderers import flextable as flextable_module
from deckifyr.renderers.flextable import FlextableExecutionConfig, render_flextable_png
from deckifyr.schema.errors import ContentValidationError, MissingDependencyError

requires_r = pytest.mark.skipif(
    shutil.which("Rscript") is None, reason="Rscript not found on PATH"
)


def _rscript_has_flextable() -> bool:
    if shutil.which("Rscript") is None:
        return False
    try:
        result = subprocess.run(
            [
                "Rscript",
                "--vanilla",
                "-e",
                "quit(status = if (requireNamespace('flextable', quietly = TRUE)) 0 else 1)",
            ],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


requires_flextable = pytest.mark.skipif(
    not _rscript_has_flextable(), reason="Rscript with the flextable package not found"
)


def _write_flextable_rds(path, *, n_rows: int = 3):
    """Generate a real `.rds` flextable fixture at test time via a real
    Rscript call -- matching `tests/python/test_pptx.py`'s own convention
    of generating fixtures in-test rather than committing binary files.
    """
    r_code = (
        "library(flextable); "
        f"df <- data.frame(name = head(letters, {n_rows}), score = seq_len({n_rows})); "
        "ft <- flextable(df); "
        f'saveRDS(ft, {str(path)!r})'
    )
    subprocess.run(
        ["Rscript", "--vanilla", "-e", r_code], check=True, capture_output=True, timeout=30
    )


# ---------------------------------------------------------------------------
# Rscript binary missing
# ---------------------------------------------------------------------------


def test_render_raises_clearly_when_rscript_missing(tmp_path):
    rds = tmp_path / "table.rds"
    rds.write_bytes(b"not a real rds file")
    config = FlextableExecutionConfig(binary="definitely-not-a-real-rscript-binary")
    with pytest.raises(ContentValidationError, match="not found on PATH"):
        render_flextable_png(rds, config=config)


def test_render_raises_a_structured_dependency_error_when_rscript_missing(tmp_path):
    # R/run-python.R's .handle_missing_dependency() reacts to this exact
    # shape (see CLAUDE.md's "Preview rendering"/"Quarto integration"
    # notes) -- pin it down so a refactor here can't silently drop the
    # `dependency` payload R depends on.
    rds = tmp_path / "table.rds"
    rds.write_bytes(b"not a real rds file")
    config = FlextableExecutionConfig(binary="definitely-not-a-real-rscript-binary")
    with pytest.raises(MissingDependencyError) as exc_info:
        render_flextable_png(rds, config=config)
    payload = exc_info.value.to_dict()
    assert payload["code"] == "E_MISSING_DEPENDENCY"
    assert payload["dependency"] == {
        "name": "rscript",
        "display_name": "R (Rscript)",
        "install_url": "https://cran.r-project.org/",
    }


# ---------------------------------------------------------------------------
# flextable package missing -- exercised deterministically via a stub R
# script, not by requiring an environment that's actually missing the
# package.
# ---------------------------------------------------------------------------


@requires_r
def test_render_raises_a_structured_dependency_error_when_flextable_package_missing(
    tmp_path, monkeypatch
):
    stub_script = tmp_path / "stub.R"
    stub_script.write_text('cat("flextable package not installed\\n", file = stderr())\nquit(status = 2, save = "no")\n')
    monkeypatch.setattr(flextable_module, "_RENDER_SCRIPT", stub_script)

    rds = tmp_path / "table.rds"
    rds.write_bytes(b"not a real rds file")
    with pytest.raises(MissingDependencyError) as exc_info:
        render_flextable_png(rds, config=FlextableExecutionConfig())
    payload = exc_info.value.to_dict()
    assert payload["code"] == "E_MISSING_DEPENDENCY"
    assert payload["dependency"] == {
        "name": "flextable",
        "display_name": "R package 'flextable'",
        "install_url": "https://cran.r-project.org/package=flextable",
    }


@requires_r
def test_render_reports_a_non_flextable_rds_object_clearly(tmp_path):
    rds = tmp_path / "table.rds"
    subprocess.run(
        ["Rscript", "--vanilla", "-e", f"saveRDS(1:3, {str(rds)!r})"],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(ContentValidationError, match="does not contain a flextable"):
        render_flextable_png(rds, config=FlextableExecutionConfig())


# ---------------------------------------------------------------------------
# Real flextable execution
# ---------------------------------------------------------------------------


@requires_flextable
def test_render_produces_a_png(tmp_path):
    rds = tmp_path / "table.rds"
    _write_flextable_rds(rds)
    png_path = render_flextable_png(rds, config=FlextableExecutionConfig())
    try:
        assert png_path.is_file()
        assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        png_path.unlink(missing_ok=True)


@requires_flextable
def test_render_png_background_is_transparent(tmp_path):
    from PIL import Image

    rds = tmp_path / "table.rds"
    _write_flextable_rds(rds)
    png_path = render_flextable_png(rds, config=FlextableExecutionConfig())
    try:
        image = Image.open(png_path)
        assert "A" in image.mode
        # A corner pixel, far from the table's own content, should be
        # fully transparent rather than opaque white.
        assert image.getpixel((0, 0))[-1] == 0
        # But the table itself did render something opaque somewhere.
        alphas = [
            image.getpixel((x, y))[-1]
            for x in range(0, image.size[0], 5)
            for y in range(0, image.size[1], 5)
        ]
        assert max(alphas) > 0
    finally:
        png_path.unlink(missing_ok=True)


@requires_flextable
def test_render_enforces_timeout(tmp_path):
    rds = tmp_path / "table.rds"
    _write_flextable_rds(rds)
    config = FlextableExecutionConfig(timeout_seconds=0.001)
    with pytest.raises(ContentValidationError, match="timeout"):
        render_flextable_png(rds, config=config)


@requires_flextable
def test_render_enforces_output_size_limit(tmp_path):
    rds = tmp_path / "table.rds"
    _write_flextable_rds(rds, n_rows=20)
    config = FlextableExecutionConfig(max_output_bytes=4)
    with pytest.raises(ContentValidationError, match="exceeds"):
        render_flextable_png(rds, config=config)
