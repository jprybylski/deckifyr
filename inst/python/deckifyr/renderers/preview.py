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
from dataclasses import dataclass
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


_LIBREOFFICE_INSTALL_URL = "https://www.libreoffice.org/download/download/"


def _require_soffice(config: PreviewRenderConfig) -> None:
    if shutil.which(config.binary) is None:
        raise MissingDependencyError(
            f"LibreOffice binary {config.binary!r} was not found on PATH -- "
            f"install LibreOffice ({_LIBREOFFICE_INSTALL_URL}) to render "
            "slide previews, or set build.preview.binary to its full path",
            name="soffice",
            display_name="LibreOffice",
            install_url=_LIBREOFFICE_INSTALL_URL,
        )


def render_slide_previews(
    pptx_path: Path, out_dir: Path, *, config: PreviewRenderConfig | None = None
) -> list[Path]:
    """Render each slide of `pptx_path` to a standalone PNG under
    `out_dir` (created if missing), one file per slide
    (`f"{pptx_path.stem}-{page:02d}.png"`, 1-indexed), returned in slide
    order.

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
            image_paths = []
            for index, page in enumerate(doc):
                image_path = out_dir / f"{pptx_path.stem}-{index + 1:02d}.png"
                page.get_pixmap(dpi=config.dpi).save(str(image_path))
                image_paths.append(image_path)
        finally:
            doc.close()
        return image_paths
