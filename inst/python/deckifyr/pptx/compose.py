"""Pass 2: resolve and compose -- the PowerPoint compositor (spec section 10).

Consumes the plan produced by `deckifyr.plan` (Pass 1) and writes an
actual `.pptx` plus a build manifest (spec section 14). Per spec section
10.2/section 20 warning 9, the one low-level OOXML workaround this needs
(`python-pptx` has no public alt-text API) is confined to `_set_alt_text`
below and must never leak into `deckifyr.schema`.

Reference-PPTX policy (spec section 21's open decision): this slice uses
`python-pptx`'s own bundled default template as the reference deck rather
than requiring a project-supplied one, and always adds slides against
that template's "Blank" layout (spec section 10.1: "known blank or
minimal native layout"). A project-supplied reference `.pptx` is a later
extension, not a v1 requirement.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation as PptxPresentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from deckifyr import __version__ as DECKIFYR_VERSION
from deckifyr.plan import ResolvedElement, ResolvedSlide
from deckifyr.resolvers import BuildContext, LocalFileResolver
from deckifyr.schema.design import DesignDocument
from deckifyr.schema.errors import ContentValidationError
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.units import parse_length

_BLANK_LAYOUT_NAME = "Blank"
_NV_PR_TAGS = ("p:nvSpPr", "p:nvPicPr", "p:nvGrpSpPr", "p:nvGraphicFramePr", "p:nvCxnSpPr")

# `design.yaml` (spec section 7.4) has no "default text style" concept
# beyond named `text_styles`; this is the engine default (spec section
# 7.2's lowest merge-precedence layer) used only when an element carries
# no `style` at all.
_DEFAULT_FONT_SIZE_PT = 18.0

# Editability classification for the manifest (spec section 10.3): every
# type this compositor supports today is either fully editable native
# PowerPoint content, or -- for images -- a graphic whose reflow depends
# on the source file rather than PowerPoint itself.
_EDITABILITY = {
    "text": "fully_editable",
    "markdown": "fully_editable",
    "image": "rendered_graphic",
}


@dataclass
class BuildResult:
    output_path: Path
    manifest_path: Path | None
    slide_count: int
    warnings: list[str] = field(default_factory=list)


def _hex_to_rgbcolor(value: str) -> RGBColor:
    return RGBColor.from_string(value.lstrip("#"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_alt_text(shape: Any, text: str) -> None:
    """Set a shape's accessibility description.

    `python-pptx` exposes no public API for this, so it's set directly on
    the shape's `nv*Pr/cNvPr` element. Confined to this one function per
    spec section 10.2's warning about isolating OOXML workarounds behind
    narrowly tested adapters.
    """
    element = shape._element
    for tag in _NV_PR_TAGS:
        nv_pr = element.find(qn(tag))
        if nv_pr is not None:
            cnv_pr = nv_pr.find(qn("p:cNvPr"))
            if cnv_pr is not None:
                cnv_pr.set("descr", text)
            return


def _find_blank_layout(prs: PptxPresentation) -> Any:
    for layout in prs.slide_layouts:
        if layout.name == _BLANK_LAYOUT_NAME:
            return layout
    return prs.slide_layouts[-1]


# ---------------------------------------------------------------------------
# Markdown: a small hand-rolled subset (headings, **bold**, *italic*), not
# full CommonMark. Real Markdown/Quarto content conversion belongs to the
# Quarto integration (spec section 8), which is Phase 2 work.
# ---------------------------------------------------------------------------

_INLINE_SPAN_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def _markdown_paragraphs(value: str) -> list[tuple[int, str]]:
    """Split into `(heading_level, text)` pairs; blank lines are dropped."""
    paragraphs: list[tuple[int, str]] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        level = len(line) - len(line.lstrip("#"))
        paragraphs.append((level, line[level:].strip()) if level else (0, line))
    return paragraphs


def _inline_spans(text: str) -> list[tuple[str, bool, bool]]:
    """Split a line into `(text, bold, italic)` spans for `**bold**`/`*italic*`."""
    spans: list[tuple[str, bool, bool]] = []
    for token in _INLINE_SPAN_RE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            spans.append((token[2:-2], True, False))
        elif token.startswith("*") and token.endswith("*"):
            spans.append((token[1:-1], False, True))
        else:
            spans.append((token, False, False))
    return spans


def _add_text_shape(slide: Any, element: ResolvedElement, design: DesignDocument) -> Any:
    shape = slide.shapes.add_textbox(
        Emu(element.x), Emu(element.y), Emu(element.width), Emu(element.height)
    )
    shape.name = element.id
    shape.rotation = element.rotation

    text_frame = shape.text_frame
    text_frame.word_wrap = True
    # Zeroed so the textbox's rendered extent matches its declared box
    # exactly (spec section 7.3's explicit-geometry model) rather than
    # python-pptx's default insets shrinking the usable area.
    text_frame.margin_left = text_frame.margin_right = Emu(0)
    text_frame.margin_top = text_frame.margin_bottom = Emu(0)

    style = element.style
    font_name = style.font if style else design.fonts.body
    font_size_pt = style.size_pt if style else _DEFAULT_FONT_SIZE_PT
    font_color = style.color if style else design.colors.get("text", "#000000")
    style_bold = style.bold if style else False
    style_italic = style.italic if style else False

    if element.type == "markdown":
        paragraphs = [
            (level, _inline_spans(text)) for level, text in _markdown_paragraphs(str(element.value))
        ]
    else:
        paragraphs = [(0, [(str(element.value), False, False)])]

    for index, (level, spans) in enumerate(paragraphs):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        for text, span_bold, span_italic in spans:
            run = paragraph.add_run()
            run.text = text
            run.font.name = font_name
            run.font.size = Pt(font_size_pt)
            # A markdown heading (`#`) is bold regardless of the resolved
            # style, same as an inline `**bold**` span.
            run.font.bold = span_bold or level > 0 or style_bold
            run.font.italic = span_italic or style_italic
            run.font.color.rgb = _hex_to_rgbcolor(font_color)

    if element.alt_text:
        _set_alt_text(shape, element.alt_text)
    return shape


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def _compute_image_placement(
    fit: str, box_width: int, box_height: int, image_width_px: int, image_height_px: int
) -> tuple[int, int, int, int, float, float, float, float]:
    """Return `(left, top, width, height, crop_left, crop_right, crop_top,
    crop_bottom)` -- `left`/`top` are offsets from the element's box
    origin, geometry in EMU, crops as fractions of the source image.
    """
    if fit == "stretch":
        return 0, 0, box_width, box_height, 0.0, 0.0, 0.0, 0.0

    image_aspect = image_width_px / image_height_px
    box_aspect = box_width / box_height

    if fit == "contain":
        if image_aspect > box_aspect:
            width, height = box_width, round(box_width / image_aspect)
        else:
            width, height = round(box_height * image_aspect), box_height
        return (box_width - width) // 2, (box_height - height) // 2, width, height, 0.0, 0.0, 0.0, 0.0

    if fit == "cover":
        if image_aspect > box_aspect:
            crop_side = (1 - box_aspect / image_aspect) / 2
            return 0, 0, box_width, box_height, crop_side, crop_side, 0.0, 0.0
        crop_edge = (1 - image_aspect / box_aspect) / 2
        return 0, 0, box_width, box_height, 0.0, 0.0, crop_edge, crop_edge

    raise ValueError(f"unhandled fit mode: {fit!r}")  # "none" is handled by the caller


def _add_image_shape(
    slide: Any, element: ResolvedElement, *, project_root: Path
) -> tuple[Any, dict[str, str]]:
    if not element.alt_text:
        raise ContentValidationError(
            f"element {element.id!r}: images require alt_text (spec section "
            "13's content validation: \"missing required alt text\")"
        )

    resolver = LocalFileResolver()
    context = BuildContext(project_root=str(project_root))
    resolved = resolver.resolve(str(element.source), context)
    image_path: Path = resolved.value

    if element.fit == "none":
        # No scaling: python-pptx sizes the picture from the image's own
        # DPI metadata, anchored at the box's top-left corner.
        shape = slide.shapes.add_picture(str(image_path), Emu(element.x), Emu(element.y))
    else:
        with Image.open(image_path) as img:
            image_width_px, image_height_px = img.size
        left, top, width, height, crop_left, crop_right, crop_top, crop_bottom = (
            _compute_image_placement(
                element.fit, element.width, element.height, image_width_px, image_height_px
            )
        )
        shape = slide.shapes.add_picture(
            str(image_path),
            Emu(element.x + left),
            Emu(element.y + top),
            width=Emu(width),
            height=Emu(height),
        )
        shape.crop_left, shape.crop_right = crop_left, crop_right
        shape.crop_top, shape.crop_bottom = crop_top, crop_bottom

    shape.name = element.id
    shape.rotation = element.rotation
    _set_alt_text(shape, element.alt_text)

    return shape, {"resolved_path": str(image_path), "sha256": _sha256_file(image_path)}


# ---------------------------------------------------------------------------
# Compose + write
# ---------------------------------------------------------------------------


def compose(
    presentation: PresentationDocument,
    design: DesignDocument,
    resolved_slides: list[ResolvedSlide],
    *,
    project_root: Path,
) -> tuple[PptxPresentation, list[dict[str, Any]]]:
    prs = PptxPresentation()
    prs.slide_width = Emu(parse_length(design.slide.width, strict=True))
    prs.slide_height = Emu(parse_length(design.slide.height, strict=True))
    blank_layout = _find_blank_layout(prs)

    element_manifest: list[dict[str, Any]] = []

    for resolved_slide in resolved_slides:
        slide = prs.slides.add_slide(blank_layout)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = _hex_to_rgbcolor(design.slide.background)

        for element in resolved_slide.elements:
            source_manifest: dict[str, str] = {}
            if element.type in ("text", "markdown"):
                _add_text_shape(slide, element, design)
            elif element.type == "image":
                _shape, source_manifest = _add_image_shape(
                    slide, element, project_root=project_root
                )
            else:  # pragma: no cover -- deckifyr.plan already rejects this
                raise ContentValidationError(
                    f"element {element.id!r}: element type {element.type!r} "
                    "is not implemented yet"
                )

            element_manifest.append(
                {
                    "slide_id": resolved_slide.id,
                    "element_id": element.id,
                    "type": element.type,
                    "render_mode": element.render_mode,
                    "editability": _EDITABILITY[element.type],
                    "overflow_policy": element.overflow,
                    **source_manifest,
                }
            )

    return prs, element_manifest


def compose_and_write(
    presentation: PresentationDocument,
    design: DesignDocument,
    resolved_slides: list[ResolvedSlide],
    *,
    project_root: Path,
    presentation_path: Path,
    design_path: Path,
    layouts_path: Path,
) -> BuildResult:
    started_at = datetime.now(timezone.utc)
    prs, element_manifest = compose(
        presentation, design, resolved_slides, project_root=project_root
    )

    output_path = (project_root / presentation.build.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    ended_at = datetime.now(timezone.utc)

    manifest = {
        "deckifyr_version": DECKIFYR_VERSION,
        "metadata": {"title": presentation.metadata.title},
        "build": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        "input_files": {
            "presentation": {
                "path": str(presentation_path),
                "sha256": _sha256_file(presentation_path),
            },
            "design": {"path": str(design_path), "sha256": _sha256_file(design_path)},
            "layouts": {"path": str(layouts_path), "sha256": _sha256_file(layouts_path)},
        },
        "slide_count": len(resolved_slides),
        "elements": element_manifest,
        "output": {"path": str(output_path), "sha256": _sha256_file(output_path)},
        "warnings": [],
    }

    manifest_path: Path | None = None
    if presentation.build.manifest:
        manifest_path = (project_root / presentation.build.manifest).resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))

    return BuildResult(
        output_path=output_path,
        manifest_path=manifest_path,
        slide_count=len(resolved_slides),
        warnings=[],
    )
