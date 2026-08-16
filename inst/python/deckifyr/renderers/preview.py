"""Slide preview rendering (spec section 12/18 Phase 3; section 21's
open "select the initial preview renderer" item -- resolved here).

`deckifyr preview`/`build.previews: true` (spec section 7.6) both need a
picture of what a built `.pptx` actually looks like. `python-pptx` has
no rendering engine of its own -- it only writes OOXML -- so a real
preview needs an external renderer. This module shells out to
LibreOffice (`soffice --headless --convert-to pdf`), the same tool this
repo's own `.githooks/pre-commit` and `examples/demo-deck/README.md`
already document as the manual recipe for regenerating
`man/figures/demo-deck-*.png`: this wires that existing, already-trusted
recipe into the CLI rather than inventing a second renderer. The
resulting PDF (one page per slide) is rasterized to PNG with PyMuPDF --
already an optional dependency for `deckifyr.renderers.quarto`'s own
`png`/`svg` render mode, imported the same lazy way here.

A LibreOffice render has real PowerPoint-engine fidelity (fonts,
gradients, tables, rotation all render the way LibreOffice's own layout
engine actually lays them out) at the cost of a real external-binary
dependency -- mirroring the `quarto` binary's own story:
`_require_soffice` raises a clear `ContentValidationError` naming the
missing binary rather than silently producing nothing, and every test
exercising a real render skips cleanly when `soffice` isn't on PATH
(see tests/python/test_renderers_preview.py), the same pattern
`test_renderers_quarto.py` already established for `quarto`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from deckifyr.schema.errors import ContentValidationError, MissingDependencyError


@dataclass
class PreviewRenderConfig:
    """Resolved `presentation.yaml` `build.preview` settings (spec
    section 7.6's `build.previews: true` is the on/off switch this
    block's own fields only matter once that -- or an explicit
    `deckifyr preview` invocation -- actually triggers a render).
    """

    binary: str = "soffice"
    dpi: int = 110
    timeout_seconds: float = 120


@dataclass
class PreviewRenderResult:
    """`render_slide_previews`'s return value -- mirrors
    `deckifyr.pptx.compose.BuildResult`'s own small-dataclass shape.
    `pdf_path` is only ever non-`None` when the caller passed
    `keep_pdf=True` (issue #27's embedded-PDF-viewer support); the
    conversion always produces an intermediate PDF internally either
    way, this just decides whether it's kept instead of discarded with
    the rest of the temp dir.
    """

    image_paths: list[Path] = field(default_factory=list)
    pdf_path: Path | None = None


# Public (not `_`-prefixed): `deckifyr.web.app`'s `GET /api/preview/availability`
# route (issue #27) reuses this exact URL for its own proactive
# "LibreOffice isn't installed" message, rather than duplicating the
# literal.
LIBREOFFICE_INSTALL_URL = "https://www.libreoffice.org/download/download/"


def _require_soffice(config: PreviewRenderConfig) -> None:
    if shutil.which(config.binary) is None:
        raise MissingDependencyError(
            f"LibreOffice binary {config.binary!r} was not found on PATH -- "
            f"install LibreOffice ({LIBREOFFICE_INSTALL_URL}) to render "
            "slide previews, or set build.preview.binary to its full path",
            name="soffice",
            display_name="LibreOffice",
            install_url=LIBREOFFICE_INSTALL_URL,
        )


def render_slide_previews(
    pptx_path: Path,
    out_dir: Path,
    *,
    config: PreviewRenderConfig | None = None,
    slides: list[int] | None = None,
    keep_pdf: bool = False,
) -> PreviewRenderResult:
    """Render each slide of `pptx_path` to a standalone PNG under
    `out_dir` (created if missing), one file per slide
    (`f"{pptx_path.stem}-{page:02d}.png"`, 1-indexed), returned in slide
    order.

    `slides` (issue #27's "preview 1, several, or all slides"): a
    1-indexed subset to rasterize -- `None` (the default) renders every
    slide, unchanged from before this parameter existed. LibreOffice
    still converts the *whole* deck to PDF either way (that's a single,
    whole-file subprocess call with no per-slide option of its own);
    `slides` only controls which pages get rasterized to PNG afterward,
    so it saves rasterization cost, not conversion cost. Raises
    `ContentValidationError` for any out-of-range index (checked after
    conversion, once the real page count is known).

    `keep_pdf`: also copy the intermediate PDF LibreOffice produces (it
    exists internally either way, just normally discarded with the rest
    of the temp dir) to `out_dir / f"{pptx_path.stem}.pdf"`, returned as
    `PreviewRenderResult.pdf_path` -- issue #27's embedded-PDF-viewer
    support, reusing this existing conversion rather than a second
    PDF-only render path.

    Raises `ContentValidationError` if `soffice` isn't on PATH, the
    conversion subprocess fails or times out, or the optional `pymupdf`
    package (this repo's `preview`/`quarto`/`dev` extra) isn't
    installed.
    """
    config = config or PreviewRenderConfig()
    _require_soffice(config)

    try:
        import pymupdf
    except ImportError as exc:
        raise ContentValidationError(
            "rendering slide previews requires the optional 'pymupdf' "
            "package (not installed) -- install deckifyr's 'preview' "
            "extra to render previews"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="deckifyr-preview-") as tmp:
        tmp_dir = Path(tmp)
        try:
            result = subprocess.run(
                [
                    config.binary,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(tmp_dir),
                    str(pptx_path),
                ],
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ContentValidationError(
                f"{pptx_path}: LibreOffice PDF conversion exceeded its "
                f"{config.timeout_seconds}s execution timeout "
                "(build.preview.timeout_seconds)"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ContentValidationError(
                f"{pptx_path}: LibreOffice PDF conversion failed:\n{detail}"
            )

        pdf_path = tmp_dir / f"{pptx_path.stem}.pdf"
        if not pdf_path.is_file():
            raise ContentValidationError(
                f"{pptx_path}: LibreOffice did not produce the expected "
                f"PDF output {pdf_path.name}"
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open(str(pdf_path))
        try:
            page_count = doc.page_count
            if slides is not None:
                for page_number in slides:
                    if not 1 <= page_number <= page_count:
                        raise ContentValidationError(
                            f"{pptx_path}: requested slide {page_number} is out "
                            f"of range -- this deck has {page_count} slide(s)"
                        )
            wanted_indices = (
                sorted(set(slides)) if slides is not None else range(1, page_count + 1)
            )
            image_paths = []
            for page_number in wanted_indices:
                page = doc[page_number - 1]
                image_path = out_dir / f"{pptx_path.stem}-{page_number:02d}.png"
                page.get_pixmap(dpi=config.dpi).save(str(image_path))
                image_paths.append(image_path)

            kept_pdf_path: Path | None = None
            if keep_pdf:
                kept_pdf_path = out_dir / f"{pptx_path.stem}.pdf"
                shutil.copy2(pdf_path, kept_pdf_path)
        finally:
            doc.close()
        return PreviewRenderResult(image_paths=image_paths, pdf_path=kept_pdf_path)
