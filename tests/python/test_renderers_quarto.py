"""Tests for `deckifyr.renderers.quarto` (spec section 8.1, issue #3).

`check_fragment_complexity`/`select_auto_render_mode` are pure text
scans -- always run. `render_native`/`render_image` shell out to a real
`quarto` binary (and, for images, the optional `pymupdf` dependency), so
those tests skip cleanly when `quarto` isn't on PATH -- mirroring
`tests/testthat/test-wiring.R`'s own uv/pyro skip pattern (see
CLAUDE.md): this is expected local/CI behavior, not a gap to work
around with mocking.
"""

from __future__ import annotations

import shutil

import pytest

from deckifyr.renderers.quarto import (
    QuartoExecutionConfig,
    check_fragment_complexity,
    render_image,
    render_native,
    select_auto_render_mode,
)
from deckifyr.schema.errors import ContentValidationError, MissingDependencyError

requires_quarto = pytest.mark.skipif(
    shutil.which("quarto") is None, reason="quarto binary not found on PATH"
)
requires_r = pytest.mark.skipif(
    shutil.which("Rscript") is None, reason="Rscript not found on PATH"
)


# ---------------------------------------------------------------------------
# Complexity limit (pure text scans, no quarto binary needed)
# ---------------------------------------------------------------------------


def test_single_fragment_passes():
    check_fragment_complexity(
        "---\ntitle: x\n---\n\nSome prose.\n\n# One heading\n\nMore prose.\n",
        label="frag.qmd",
    )


def test_frontmatter_delimiters_are_not_a_slide_break():
    # The frontmatter's own `---` fence lines must not be mistaken for a
    # slide-break horizontal rule.
    check_fragment_complexity("---\ntitle: x\n---\n\nJust prose.\n", label="frag.qmd")


def test_extra_horizontal_rule_rejected():
    with pytest.raises(ContentValidationError, match="slide/section break"):
        check_fragment_complexity(
            "Some prose.\n\n---\n\nMore content after a slide break.\n", label="frag.qmd"
        )


def test_multiple_top_level_headings_rejected():
    with pytest.raises(ContentValidationError, match="more than one"):
        check_fragment_complexity(
            "# First section\n\nprose\n\n# Second section\n\nprose\n", label="frag.qmd"
        )


def test_hash_inside_code_fence_is_not_a_heading():
    source = "```r\n# this is an R comment, not a heading\n# another one\n```\n"
    check_fragment_complexity(source, label="frag.qmd")


def test_dashes_inside_code_fence_are_not_a_slide_break():
    source = "```\n---\nnot a slide break, just fenced output\n```\n"
    check_fragment_complexity(source, label="frag.qmd")


# ---------------------------------------------------------------------------
# render_mode: auto heuristic
# ---------------------------------------------------------------------------


def test_auto_prefers_native_for_plain_prose():
    assert select_auto_render_mode("Just some plain prose, no code or math.\n") == "native"


def test_auto_picks_png_for_display_math():
    assert select_auto_render_mode("The formula is:\n\n$$x^2 + y^2 = z^2$$\n") == "png"


def test_auto_picks_png_for_a_code_chunk():
    assert select_auto_render_mode("```{r}\n1 + 1\n```\n") == "png"


def test_auto_ignores_math_looking_text_inside_a_fence():
    source = "```\nplain code, no math: $$ literally just dollar signs $$\n```\n"
    assert select_auto_render_mode(source) == "native"


# ---------------------------------------------------------------------------
# quarto binary missing
# ---------------------------------------------------------------------------


def test_render_native_raises_clearly_when_quarto_missing(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("Hello.\n")
    config = QuartoExecutionConfig(binary="definitely-not-a-real-quarto-binary")
    with pytest.raises(ContentValidationError, match="not found on PATH"):
        render_native(qmd, config=config)


def test_render_native_raises_a_structured_dependency_error_when_quarto_missing(tmp_path):
    # R/run-python.R's .handle_missing_dependency() reacts to this exact
    # shape (see CLAUDE.md's "Preview rendering" note) -- pin it down so
    # a refactor here can't silently drop the `dependency` payload R
    # depends on.
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("Hello.\n")
    config = QuartoExecutionConfig(binary="definitely-not-a-real-quarto-binary")
    with pytest.raises(MissingDependencyError) as exc_info:
        render_native(qmd, config=config)
    payload = exc_info.value.to_dict()
    assert payload["code"] == "E_MISSING_DEPENDENCY"
    assert payload["dependency"] == {
        "name": "quarto",
        "display_name": "Quarto",
        "install_url": "https://quarto.org/docs/get-started/",
    }


# ---------------------------------------------------------------------------
# Real quarto execution
# ---------------------------------------------------------------------------


@requires_quarto
def test_render_native_returns_executed_markdown(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("The answer is **42**.\n")
    text = render_native(qmd, config=QuartoExecutionConfig())
    assert "42" in text
    assert "**42**" in text or "__42__" in text  # GFM keeps bold emphasis markers


@requires_quarto
@requires_r
def test_render_native_executes_r_code(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text(
        "```{r}\n#| echo: false\nx <- 2 + 2\n```\n\nThe computed value is `r x`.\n"
    )
    text = render_native(qmd, config=QuartoExecutionConfig())
    assert "The computed value is 4." in text


@requires_quarto
def test_render_native_rejects_multi_slide_fragment(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("# One\n\nprose\n\n# Two\n\nprose\n")
    with pytest.raises(ContentValidationError):
        render_native(qmd, config=QuartoExecutionConfig())


@requires_quarto
def test_render_native_enforces_timeout(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("Hello.\n")
    config = QuartoExecutionConfig(timeout_seconds=0.001)
    with pytest.raises(ContentValidationError, match="timeout"):
        render_native(qmd, config=config)


@requires_quarto
def test_render_native_enforces_output_size_limit(tmp_path):
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("Hello, this is more than a couple bytes of prose.\n")
    config = QuartoExecutionConfig(max_output_bytes=4)
    with pytest.raises(ContentValidationError, match="exceeds"):
        render_native(qmd, config=config)


@requires_quarto
def test_render_image_produces_svg_and_png(tmp_path):
    pytest.importorskip("pymupdf")
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("The quadratic formula is:\n\n$$x = \\frac{-b}{2a}$$\n")
    config = QuartoExecutionConfig()

    svg_path = render_image(qmd, image_format="svg", config=config)
    try:
        assert svg_path.is_file()
        assert svg_path.suffix == ".svg"
        assert b"<svg" in svg_path.read_bytes()[:200]
    finally:
        svg_path.unlink(missing_ok=True)

    png_path = render_image(qmd, image_format="png", config=config)
    try:
        assert png_path.is_file()
        assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        png_path.unlink(missing_ok=True)


@requires_quarto
def test_render_image_png_background_is_transparent(tmp_path):
    # Issue #9: a rasterized fragment's background used to composite onto
    # opaque white regardless of what it sat on top of in the deck.
    pytest.importorskip("pymupdf")
    from PIL import Image

    qmd = tmp_path / "frag.qmd"
    qmd.write_text("Some prose to rasterize.\n")
    png_path = render_image(qmd, image_format="png", config=QuartoExecutionConfig())
    try:
        image = Image.open(png_path)
        assert "A" in image.mode
        # A corner pixel, far from any glyph, should be fully transparent
        # rather than opaque white.
        assert image.getpixel((0, 0))[-1] == 0
    finally:
        png_path.unlink(missing_ok=True)


@requires_quarto
def test_render_image_cleans_up_sibling_fragment(tmp_path):
    pytest.importorskip("pymupdf")
    qmd = tmp_path / "frag.qmd"
    qmd.write_text("$$x^2$$\n")
    image_path = render_image(qmd, image_format="svg", config=QuartoExecutionConfig())
    image_path.unlink(missing_ok=True)

    leftovers = [p for p in tmp_path.iterdir() if p.name != "frag.qmd"]
    assert leftovers == []
