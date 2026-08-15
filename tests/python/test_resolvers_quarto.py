"""Tests for `deckifyr.resolvers.quarto.QuartoResolver` (spec section
9.2, issue #3). Path-safety/existence checks run unconditionally (they
raise before ever invoking `quarto`); the rest requires a real `quarto`
binary -- see `test_renderers_quarto.py`'s own note on this skip
pattern.
"""

from __future__ import annotations

import shutil

import pytest

from deckifyr.resolvers import BuildContext, QuartoResolver
from deckifyr.schema.errors import ContentValidationError

requires_quarto = pytest.mark.skipif(
    shutil.which("quarto") is None, reason="quarto binary not found on PATH"
)


def test_supports_only_qmd_sources():
    resolver = QuartoResolver()
    assert resolver.supports("fragments/interp.qmd") is True
    assert resolver.supports("figures/plot.png") is False
    assert resolver.supports("{rpfy}:something.qmd") is False


def test_rejects_path_outside_project_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.qmd"
    outside.write_text("Hello.\n")

    with pytest.raises(ContentValidationError, match="outside the project root"):
        QuartoResolver().resolve(
            "../outside.qmd", BuildContext(project_root=str(project))
        )


def test_missing_source_raises(tmp_path):
    with pytest.raises(ContentValidationError, match="not found"):
        QuartoResolver().resolve(
            "missing.qmd", BuildContext(project_root=str(tmp_path))
        )


@requires_quarto
def test_resolve_native_returns_markdown(tmp_path):
    (tmp_path / "frag.qmd").write_text("Hello, **world**.\n")
    resolved = QuartoResolver().resolve(
        "frag.qmd", BuildContext(project_root=str(tmp_path)), requested_render_mode="native"
    )
    artifact = resolved.value
    assert artifact.render_mode == "native"
    assert "world" in artifact.markdown
    assert artifact.image_path is None


@requires_quarto
def test_resolve_auto_picks_png_for_math(tmp_path):
    pytest.importorskip("pymupdf")
    (tmp_path / "frag.qmd").write_text("$$x^2$$\n")
    resolved = QuartoResolver().resolve(
        "frag.qmd", BuildContext(project_root=str(tmp_path)), requested_render_mode="auto"
    )
    artifact = resolved.value
    try:
        assert artifact.render_mode == "png"
        assert artifact.image_path is not None and artifact.image_path.is_file()
    finally:
        if artifact.image_path is not None:
            artifact.image_path.unlink(missing_ok=True)


@requires_quarto
def test_resolve_auto_picks_native_for_prose(tmp_path):
    (tmp_path / "frag.qmd").write_text("Plain prose, nothing fancy.\n")
    resolved = QuartoResolver().resolve(
        "frag.qmd", BuildContext(project_root=str(tmp_path)), requested_render_mode="auto"
    )
    assert resolved.value.render_mode == "native"
