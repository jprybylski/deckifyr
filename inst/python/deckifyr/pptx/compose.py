"""Pass 2: resolve and compose -- the PowerPoint compositor (spec section 10).

Consumes the plan produced by `deckifyr.plan` (Pass 1) and writes an
actual `.pptx` plus a build manifest (spec section 14). Per spec section
10.2/section 20 warning 9, the one low-level OOXML workaround this needs
(`python-pptx` has no public alt-text API) is confined to `_set_alt_text`
below and must never leak into `deckifyr.schema`.

Reference-PPTX policy (spec section 10.1/section 21, decided -- not an
open v1 slice): this always composes against `python-pptx`'s own bundled
default template, adding slides against that template's "Blank" layout
(spec section 10.1's "known blank or minimal native layout"). A
project-supplied reference `.pptx` is deliberately descoped, not
deferred -- it would reintroduce the hand-clicked template artifact
Deckifyr exists to replace, and would contribute nothing that
`design.yaml`'s tokens and `furniture` block (spec section 7.8) don't
already provide, since no element here inherits color/font from native
theme. Don't add a `--reference-pptx`-style flag or schema field; that
was considered and rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation as PptxPresentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from deckifyr import __version__ as DECKIFYR_VERSION
from deckifyr.plan import (
    ResolvedElement,
    ResolvedGradient,
    ResolvedSlide,
    ResolvedTableStyle,
    ResolvedTextStyle,
    resolve_gradient,
    resolve_text_style,
)
from deckifyr.renderers.preview import PreviewRenderConfig, render_slide_previews
from deckifyr.renderers.quarto import QuartoExecutionConfig
from deckifyr.resolvers import (
    BuildContext,
    LocalFileResolver,
    QuartoArtifact,
    QuartoResolver,
    ReportifyrArtifact,
    ReportifyrResolver,
    TableData,
    TableResolver,
    build_footer_lines,
    load_standard_footnotes,
    split_scripts,
)
from deckifyr.resolvers.reportifyr import MAGIC_PREFIX
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
# on the source file rather than PowerPoint itself. `quarto` has no
# single answer here -- it depends on the *resolved* render_mode
# (native text vs. a rasterized svg/png) -- so `_compose_element`
# overrides this default per element rather than using it directly; see
# `_add_quarto_shape`.
_EDITABILITY = {
    "text": "fully_editable",
    "markdown": "fully_editable",
    "image": "rendered_graphic",
    "shape": "fully_editable",
    "group": "fully_editable",
    "table": "fully_editable",
    "reportifyr": "rendered_graphic",
    "quarto": "rendered_graphic",
}

# Footer text fallback (spec section 9.1) used when `design.yaml`'s
# `defaults.footer_style` names no `text_styles` entry -- a small,
# unobtrusive default rather than the ordinary body-text size, matching
# the kind of size a Word document's own footnotes use. A complete
# `ResolvedTextStyle`, not a hand-picked subset of fields, so it's a
# drop-in stand-in for a real named style -- see `_resolve_footer_style`.
_DEFAULT_FOOTER_FONT_NAME = "Arial Narrow"
_DEFAULT_FOOTER_FONT_SIZE_PT = 10.0
_DEFAULT_FOOTER_COLOR = "#5F6368"
_DEFAULT_FOOTER_STYLE = ResolvedTextStyle(
    font=_DEFAULT_FOOTER_FONT_NAME,
    size_pt=_DEFAULT_FOOTER_FONT_SIZE_PT,
    bold=False,
    italic=False,
    color=_DEFAULT_FOOTER_COLOR,
    opacity=None,
    text_transform=None,
)

# Border weight applied when a `table_style` sets `border_color` but no
# `border_width` (mirrors `ShapeStyle`'s own "color set, width unset"
# case having a sane hairline default rather than requiring every field).
_DEFAULT_TABLE_BORDER_WIDTH_PT = 0.75

# `deckifyr.schema.layouts.ShapeKind`'s values, mapped to their
# `MSO_SHAPE` member. Keep in sync with that Literal -- schema validation
# already guarantees every `shape_kind` reaching this module is one of
# these keys, so a lookup miss here is a bug, not a user error.
_SHAPE_KIND_MAP = {
    "rectangle": MSO_SHAPE.RECTANGLE,
    "rounded_rectangle": MSO_SHAPE.ROUNDED_RECTANGLE,
    "oval": MSO_SHAPE.OVAL,
    "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "diamond": MSO_SHAPE.DIAMOND,
    "pentagon": MSO_SHAPE.PENTAGON,
    "hexagon": MSO_SHAPE.HEXAGON,
    "chevron": MSO_SHAPE.CHEVRON,
    "right_arrow": MSO_SHAPE.RIGHT_ARROW,
    "left_arrow": MSO_SHAPE.LEFT_ARROW,
    "up_arrow": MSO_SHAPE.UP_ARROW,
    "down_arrow": MSO_SHAPE.DOWN_ARROW,
    "star_5": MSO_SHAPE.STAR_5_POINT,
}

# Shape defaults (spec section 21-style pragmatic choice, not spec text):
# a style-less shape still renders as a visible, thin black outline rather
# than an invisible one, since an all-default shape with no fill and no
# line would otherwise place nothing a viewer can actually see.
_DEFAULT_LINE_COLOR = "#000000"
_DEFAULT_LINE_WIDTH_PT = 1.0

# `a:`-namespaced raw XML built by hand for the OOXML gaps `python-pptx`
# has no public API for -- table-cell borders (`_set_cell_borders`) and
# arbitrary-length gradient stop lists (`_apply_gradient`).
_DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


@dataclass
class BuildResult:
    output_path: Path
    manifest_path: Path | None
    slide_count: int
    warnings: list[str] = field(default_factory=list)
    preview_paths: list[Path] = field(default_factory=list)
    # Only non-`None` when `compose_and_write`'s `keep_preview_pdf=True`
    # (issue #27's embedded-PDF-viewer support, `deckifyr preview`'s own
    # always-on choice -- see that CLI command's own comment).
    preview_pdf_path: Path | None = None


@dataclass
class ReportifyrBuildContext:
    """Assembled once per build from `presentation.build.reportifyr`
    (spec section 9.1), not re-read per element. `standard_footnotes`
    is `None` when the project hasn't configured one -- distinct from
    `{}` (configured, but the file happens to define nothing) so a
    reportifyr-sourced element that actually needs a footer can raise a
    clear "you haven't set build.reportifyr.standard_footnotes" error
    rather than a confusing "meta_type not found in {}" one.
    """

    outputs_dir: str = "OUTPUTS"
    fail_on_missing_metadata: bool = True
    standard_footnotes: dict[str, Any] | None = None
    footer_style: ResolvedTextStyle = field(default_factory=lambda: _DEFAULT_FOOTER_STYLE)


def _resolve_footer_style(design: DesignDocument) -> ResolvedTextStyle:
    """The complete style a reportifyr footer renders with -- every field
    `resolve_text_style` returns (font, size, color, bold, italic), not a
    hand-picked subset, so a `TextStyle` field added later is inherited
    by footers automatically rather than needing a second update here.
    `design.yaml`'s `defaults.footer_style` names the `text_styles` entry
    to use; unset falls back to `_DEFAULT_FOOTER_STYLE`, itself a
    complete `ResolvedTextStyle` so both branches are the same shape.
    """
    style_name = design.defaults.footer_style
    if style_name is not None:
        return resolve_text_style(design, style_name)
    return ResolvedTextStyle(
        font=_DEFAULT_FOOTER_STYLE.font,
        size_pt=_DEFAULT_FOOTER_STYLE.size_pt,
        bold=_DEFAULT_FOOTER_STYLE.bold,
        italic=_DEFAULT_FOOTER_STYLE.italic,
        color=design.colors.get("muted", _DEFAULT_FOOTER_COLOR),
        opacity=_DEFAULT_FOOTER_STYLE.opacity,
        text_transform=_DEFAULT_FOOTER_STYLE.text_transform,
    )


def _build_reportifyr_context(
    presentation: PresentationDocument, design: DesignDocument, *, project_root: Path
) -> ReportifyrBuildContext:
    footer_style = _resolve_footer_style(design)
    config = presentation.build.reportifyr
    if config is None:
        return ReportifyrBuildContext(footer_style=footer_style)
    standard_footnotes = (
        load_standard_footnotes(project_root / config.standard_footnotes)
        if config.standard_footnotes
        else None
    )
    return ReportifyrBuildContext(
        outputs_dir=config.outputs_dir,
        fail_on_missing_metadata=config.fail_on_missing_metadata,
        standard_footnotes=standard_footnotes,
        footer_style=footer_style,
    )


def _build_quarto_config(presentation: PresentationDocument) -> QuartoExecutionConfig:
    """Assembled once per build from `presentation.build.quarto` (spec
    section 8.1), mirroring `_build_reportifyr_context` -- a build with
    no `quarto` element never reads it, and an absent `build.quarto`
    block just means every `QuartoExecutionConfig` default applies.
    """
    config = presentation.build.quarto
    if config is None:
        return QuartoExecutionConfig()
    return QuartoExecutionConfig(
        binary=config.binary,
        timeout_seconds=config.timeout_seconds,
        max_output_bytes=config.max_output_bytes,
    )


def _build_preview_config(presentation: PresentationDocument) -> PreviewRenderConfig:
    """Assembled once per build from `presentation.build.preview`,
    mirroring `_build_quarto_config` -- a build that never renders
    previews (neither `build.previews: true` nor `force_previews`) never
    reads it, and an absent `build.preview` block just means every
    `PreviewRenderConfig` default applies.
    """
    config = presentation.build.preview
    if config is None:
        return PreviewRenderConfig()
    return PreviewRenderConfig(
        binary=config.binary, dpi=config.dpi, timeout_seconds=config.timeout_seconds
    )


def _hex_to_rgbcolor(value: str) -> RGBColor:
    return RGBColor.from_string(value.lstrip("#"))


def _apply_gradient(fill: Any, gradient: ResolvedGradient) -> None:
    """Set a `FillFormat` (a shape's own `shape.fill`, or a slide's
    `slide.background.fill`) to a linear gradient with an arbitrary
    number of stops.

    `python-pptx`'s own `FillFormat.gradient()` establishes a gradient
    with a fixed two default stops, and its `gradient_stops` collection
    (`_GradientStops`) is a read/write-in-place `Sequence` with no public
    way to add or remove stops -- confirmed directly against its source,
    not assumed from docs. So this rebuilds the `<a:gsLst>` element's
    children via lxml, the same confined-OOXML-workaround pattern
    `_set_cell_borders` above uses for a different `python-pptx` gap,
    verified against a real `.pptx` reopened with `python-pptx` (2+ and
    3-stop cases both round-tripped their exact stop colors/positions and
    gradient angle). `fill.gradient()` is still called first -- it's what
    actually switches the fill type to gradient and installs the `<a:lin>`
    element `gradient_angle`'s setter requires -- this only replaces the
    stop list underneath it and reuses the public `gradient_angle` setter
    for the angle itself.
    """
    fill.gradient()
    grad_fill = fill._xPr.get_or_change_to_gradFill()
    gs_lst = grad_fill.gsLst
    for gs in list(gs_lst):
        gs_lst.remove(gs)
    for stop in gradient.stops:
        rgb = stop.color.lstrip("#")
        pos = int(round(stop.position * 100000))
        gs = parse_xml(f'<a:gs xmlns:a="{_DRAWINGML_NS}" pos="{pos}"><a:srgbClr val="{rgb}"/></a:gs>')
        gs_lst.append(gs)
    fill.gradient_angle = gradient.angle


def _apply_text_alpha(run: Any, opacity: float) -> None:
    """Set a text run's fill opacity (`TextStyle.opacity`, spec section
    7.4). `python-pptx` has no public API for run color alpha --
    `ColorFormat` only models the color itself -- so this appends an
    `<a:alpha>` child directly to the `<a:srgbClr>` element
    `run.font.color.rgb`'s own setter already created, the same confined
    lxml pattern `_set_cell_borders`/`_apply_gradient` use for other
    `python-pptx` gaps, verified against a real `.pptx` reopened with
    `python-pptx` (the alpha child round-tripped exactly). Must run after
    `run.font.color.rgb` is set -- that's what creates the `<a:srgbClr>`
    element this appends to.
    """
    rPr = run._r.get_or_add_rPr()
    srgb_clr = rPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
    val = int(round(opacity * 100000))
    srgb_clr.append(parse_xml(f'<a:alpha xmlns:a="{_DRAWINGML_NS}" val="{val}"/>'))


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
# full CommonMark. `_add_quarto_shape`'s `render_mode: native` path
# reuses this same subset for a Quarto fragment's GFM output rather than
# a second Markdown renderer -- real CommonMark/table support remains
# out of scope for both.
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


_TEXT_ALIGN = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
}


def _apply_text_transform(text: str, transform: str | None) -> str:
    """Apply a `TextStyle.text_transform` case transform (spec section
    7.4) to one run's text. `None`/`"none"` (the vast majority of
    styles) is a no-op; every other value is a plain `str` method, not
    an OOXML feature -- unlike `opacity`, there's no `python-pptx` gap
    to work around here.
    """
    if transform == "uppercase":
        return text.upper()
    if transform == "lowercase":
        return text.lower()
    if transform == "capitalize":
        return text.title()
    return text


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
    if element.center:
        text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE

    style = element.style
    font_name = style.font if style else design.fonts.body
    font_size_pt = style.size_pt if style else _DEFAULT_FONT_SIZE_PT
    font_color = style.color if style else design.colors.get("text", "#000000")
    style_bold = style.bold if style else False
    style_italic = style.italic if style else False
    font_opacity = style.opacity if style else None
    text_transform = style.text_transform if style else None

    if element.type == "markdown":
        paragraphs = [
            (level, _inline_spans(text)) for level, text in _markdown_paragraphs(str(element.value))
        ]
    else:
        paragraphs = [(0, [(str(element.value), False, False)])]

    horizontal_align = _TEXT_ALIGN.get(element.align)
    if horizontal_align is None and element.center:
        horizontal_align = PP_ALIGN.CENTER

    for index, (level, spans) in enumerate(paragraphs):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        if horizontal_align is not None:
            paragraph.alignment = horizontal_align
        for text, span_bold, span_italic in spans:
            run = paragraph.add_run()
            run.text = _apply_text_transform(text, text_transform)
            run.font.name = font_name
            run.font.size = Pt(font_size_pt)
            # A markdown heading (`#`) is bold regardless of the resolved
            # style, same as an inline `**bold**` span.
            run.font.bold = span_bold or level > 0 or style_bold
            run.font.italic = span_italic or style_italic
            run.font.color.rgb = _hex_to_rgbcolor(font_color)
            if font_opacity is not None:
                _apply_text_alpha(run, font_opacity)

    if element.alt_text:
        _set_alt_text(shape, element.alt_text)
    return shape


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def _add_autoshape(slide: Any, element: ResolvedElement) -> Any:
    mso_shape = _SHAPE_KIND_MAP[element.shape_kind]
    shape = slide.shapes.add_shape(
        mso_shape, Emu(element.x), Emu(element.y), Emu(element.width), Emu(element.height)
    )
    shape.name = element.id
    shape.rotation = element.rotation

    style = element.shape_style
    fill = style.fill if style else None
    line_color = style.line_color if (style and style.line_color) else _DEFAULT_LINE_COLOR
    line_width_pt = (
        style.line_width_pt if (style and style.line_width_pt) else _DEFAULT_LINE_WIDTH_PT
    )

    if isinstance(fill, ResolvedGradient):
        _apply_gradient(shape.fill, fill)
    elif fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _hex_to_rgbcolor(fill)
    else:
        shape.fill.background()

    if line_color:
        shape.line.color.rgb = _hex_to_rgbcolor(line_color)
        shape.line.width = Pt(line_width_pt)
    else:
        shape.line.fill.background()

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


def _place_picture(slide: Any, element: ResolvedElement, image_path: Path) -> Any:
    """The actual `add_picture` placement, shared by `image` and
    `reportifyr` elements (spec section 9.1's figures are just images
    with a `{rpfy}:`-resolved source) -- everything except how
    `image_path` itself gets resolved.
    """
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
    if element.alt_text:
        _set_alt_text(shape, element.alt_text)

    return shape


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
    image_path: Path = resolver.resolve(str(element.source), context).value

    shape = _place_picture(slide, element, image_path)
    return shape, {"resolved_path": str(image_path), "sha256": _sha256_file(image_path)}


# ---------------------------------------------------------------------------
# Reportifyr figures + footers
# ---------------------------------------------------------------------------


def _set_baseline(run: Any, script: str) -> None:
    """Subscript/superscript (spec section 20 warning 7's "don't
    silently degrade content", applied to `standard_footnotes.yaml`'s
    own `_{...}`/`^{...}` notation). `python-pptx` exposes no public
    subscript/superscript API, so -- like `_set_alt_text` above -- this
    sets the OOXML `baseline` attribute directly, confined to this one
    function.
    """
    if script == "sub":
        run.font._rPr.set("baseline", "-25000")
    elif script == "sup":
        run.font._rPr.set("baseline", "30000")


def _add_footer_shape(
    slide: Any,
    element: ResolvedElement,
    lines: list[str],
    design: DesignDocument,
    style: ResolvedTextStyle,
) -> Any:
    height = parse_length(design.defaults.footer_height, strict=True)

    shape = slide.shapes.add_textbox(
        Emu(element.x), Emu(element.y + element.height), Emu(element.width), Emu(height)
    )
    shape.name = f"{element.id}__footer"

    text_frame = shape.text_frame
    text_frame.word_wrap = True
    text_frame.margin_left = text_frame.margin_right = Emu(0)
    text_frame.margin_top = text_frame.margin_bottom = Emu(0)

    font_rgb = _hex_to_rgbcolor(style.color)
    for index, line in enumerate(lines):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        for segment in split_scripts(line):
            run = paragraph.add_run()
            run.text = segment.text
            # Every field `style` carries is applied, not a hand-picked
            # subset -- see `_resolve_footer_style`'s docstring.
            run.font.name = style.font
            run.font.size = Pt(style.size_pt)
            run.font.bold = style.bold
            run.font.italic = style.italic
            run.font.color.rgb = font_rgb
            _set_baseline(run, segment.script)

    return shape


def _apply_footer(
    slide: Any,
    element: ResolvedElement,
    artifact_type: str,
    metadata: dict[str, Any] | None,
    reportifyr_ctx: ReportifyrBuildContext,
    design: DesignDocument,
) -> str | None:
    """Builds footer text for a reportifyr-sourced element and, per
    `footer_placement`, either places it as a shape (`"below"`, this
    slice's default) or returns it for the caller to append to the
    slide's speaker notes (`"notes"`) -- `None` either when there's
    nothing to show or when it was already placed as a shape.
    """
    if element.footer_placement is None or element.footer_placement == "none":
        return None
    if metadata is None:
        # A missing sidecar only reaches here when
        # `fail_on_missing_metadata: false` let resolution succeed
        # anyway (already recorded as a build warning) -- there's simply
        # no footnote content to show.
        return None
    if reportifyr_ctx.standard_footnotes is None:
        raise ContentValidationError(
            f"element {element.id!r}: a reportifyr footer requires "
            "build.reportifyr.standard_footnotes to be set in "
            "presentation.yaml (or set footer_placement: none to skip it)"
        )

    lines = build_footer_lines(metadata, artifact_type, reportifyr_ctx.standard_footnotes)
    if not lines:
        return None
    if element.footer_placement == "below":
        _add_footer_shape(slide, element, lines, design, reportifyr_ctx.footer_style)
        return None
    return "\n".join(lines)


def _add_reportifyr_shape(
    slide: Any,
    element: ResolvedElement,
    reportifyr_ctx: ReportifyrBuildContext,
    design: DesignDocument,
    *,
    project_root: Path,
) -> tuple[Any, dict[str, str], list[str], str | None]:
    if not element.alt_text:
        raise ContentValidationError(
            f"element {element.id!r}: reportifyr figures require alt_text "
            "(spec section 13's content validation: \"missing required alt text\")"
        )

    resolver = ReportifyrResolver(
        outputs_dir=reportifyr_ctx.outputs_dir,
        fail_on_missing_metadata=reportifyr_ctx.fail_on_missing_metadata,
    )
    context = BuildContext(project_root=str(project_root))
    artifact: ReportifyrArtifact = resolver.resolve(str(element.value), context).value

    shape = _place_picture(slide, element, artifact.path)
    footer_note = _apply_footer(slide, element, "figure", artifact.metadata, reportifyr_ctx, design)

    source_manifest = {"resolved_path": str(artifact.path), "sha256": _sha256_file(artifact.path)}
    return shape, source_manifest, list(artifact.warnings), footer_note


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _set_cell_borders(cell: Any, *, color: str, width_pt: float) -> None:
    """Set all four sides of a table cell's border to a uniform color/width.

    `python-pptx` exposes no public API for table-cell borders at all --
    `CT_TableCellProperties` (`a:tcPr`) only models fill/margin/anchor,
    not the `<a:lnL>/<a:lnR>/<a:lnT>/<a:lnB>` line elements OOXML's own
    schema allows there -- so this builds them directly via lxml,
    confined to this one function per spec section 10.2's warning about
    isolating OOXML workarounds behind narrowly tested adapters (the
    same pattern `_set_alt_text` above uses). Must run before this same
    cell's `cell.fill.solid()` is called: OOXML orders `a:tcPr`'s border
    children ahead of its fill child, and `python-pptx`'s own fill-
    insertion logic doesn't know these undeclared siblings exist, so it
    only lands after them if they're already present when fill is set.
    """
    tcPr = cell._tc.get_or_add_tcPr()
    width_emu = int(Pt(width_pt))
    rgb = color.lstrip("#")
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        line = parse_xml(
            f'<{tag} xmlns:a="{_DRAWINGML_NS}" w="{width_emu}">'
            f'<a:solidFill><a:srgbClr val="{rgb}"/></a:solidFill>'
            f"</{tag}>"
        )
        tcPr.append(line)


def _apply_table_chrome(
    table: Any, style: ResolvedTableStyle, *, row_count: int, col_count: int
) -> None:
    """Apply a `table_style`'s fill/border chrome on top of whatever
    `python-pptx`'s own default table template already drew (spec
    section 10.1). Every field on `style` is independently optional --
    an unset field leaves that aspect of the default template alone,
    the same "token or literal, else built-in default" convention
    `ShapeStyle` uses -- so setting only `header_fill`, say, changes
    nothing about banding or borders.
    """
    border_width_pt = (
        style.border_width_pt
        if style.border_width_pt is not None
        else _DEFAULT_TABLE_BORDER_WIDTH_PT
    )
    for row_index in range(row_count):
        if row_index == 0:
            fill_color = style.header_fill
        elif style.band_fill is not None and (row_index - 1) % 2 == 1:
            fill_color = style.band_fill
        else:
            fill_color = style.body_fill
        for col_index in range(col_count):
            cell = table.cell(row_index, col_index)
            if style.border_color is not None:
                _set_cell_borders(cell, color=style.border_color, width_pt=border_width_pt)
            if fill_color is not None:
                cell.fill.solid()
                cell.fill.fore_color.rgb = _hex_to_rgbcolor(fill_color)


def _add_table_shape(
    slide: Any,
    element: ResolvedElement,
    design: DesignDocument,
    reportifyr_ctx: ReportifyrBuildContext,
    *,
    project_root: Path,
) -> tuple[Any, dict[str, str], list[str], str | None]:
    context = BuildContext(project_root=str(project_root))
    source = str(element.source)
    warnings: list[str] = []
    metadata: dict[str, Any] | None = None

    if source.startswith(MAGIC_PREFIX):
        # A `{rpfy}:`-sourced table: resolve the magic string to a
        # concrete path/sidecar first, then hand that path to the same
        # CSV/Parquet `TableResolver` logic a plain local `source` uses
        # -- `TableResolver` itself only knows project-relative strings,
        # so re-derive one from the already-resolved, already-verified-
        # inside-the-project absolute path (mirroring the existing
        # double-resolve pattern below for a plain local source).
        resolver = ReportifyrResolver(
            outputs_dir=reportifyr_ctx.outputs_dir,
            fail_on_missing_metadata=reportifyr_ctx.fail_on_missing_metadata,
        )
        artifact: ReportifyrArtifact = resolver.resolve(source, context).value
        table_path = artifact.path
        metadata = artifact.metadata
        warnings.extend(artifact.warnings)
        relative_source = str(table_path.relative_to(project_root))
        data: TableData = TableResolver().resolve(relative_source, context).value
    else:
        # Two resolves of the same `source`, deliberately: `LocalFileResolver`
        # gives the path this function needs for the manifest's
        # `resolved_path`/`sha256` (the same fields every other file-backed
        # element records), while `TableResolver` gives the parsed content --
        # mirroring the resolver-per-concern split spec section 9.2 lays out
        # rather than having `TableResolver` reach back into path bookkeeping
        # that isn't its job.
        table_path = LocalFileResolver().resolve(source, context).value
        data = TableResolver().resolve(source, context).value

    if not data.headers:
        raise ContentValidationError(
            f"element {element.id!r}: table source {element.source!r} has no columns"
        )

    row_count = 1 + len(data.rows)
    col_count = len(data.headers)
    graphic_frame = slide.shapes.add_table(
        row_count,
        col_count,
        Emu(element.x),
        Emu(element.y),
        Emu(element.width),
        Emu(element.height),
    )
    graphic_frame.name = element.id
    graphic_frame.rotation = element.rotation
    table = graphic_frame.table

    style = element.style
    font_name = style.font if style else design.fonts.body
    font_size_pt = style.size_pt if style else _DEFAULT_FONT_SIZE_PT
    font_color = style.color if style else design.colors.get("text", "#000000")
    style_italic = style.italic if style else False

    def _fill_cell(
        row: int, col: int, text: str, *, bold: bool, apply_color: bool, text_color: str | None = None
    ) -> None:
        cell = table.cell(row, col)
        cell.text = text
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.name = font_name
        run.font.size = Pt(font_size_pt)
        run.font.bold = bold
        run.font.italic = style_italic
        # The default table style (python-pptx's bundled template, spec
        # section 10.1) already colors the header row for contrast against
        # its own fill (light text on a solid band). A `table` element's
        # `style` is meant for body text color against the slide
        # background, not the header's fill, so it's applied to data rows
        # only -- forcing it onto the header would fight the theme's own
        # contrast choice (e.g. `footnote`'s muted gray unreadable on a
        # dark header band). `text_color` is the one explicit override to
        # that rule: a `table_style.header_text_color` the author set on
        # purpose, typically paired with a `header_fill` that would
        # otherwise fight the template's own inherited header text color.
        if text_color is not None:
            run.font.color.rgb = _hex_to_rgbcolor(text_color)
        elif apply_color:
            run.font.color.rgb = _hex_to_rgbcolor(font_color)

    header_text_color = element.table_style.header_text_color if element.table_style else None
    for col_index, header in enumerate(data.headers):
        _fill_cell(0, col_index, header, bold=True, apply_color=False, text_color=header_text_color)
    for row_index, row in enumerate(data.rows, start=1):
        for col_index, value in enumerate(row):
            _fill_cell(row_index, col_index, value, bold=False, apply_color=True)

    if element.table_style is not None:
        _apply_table_chrome(table, element.table_style, row_count=row_count, col_count=col_count)

    if element.alt_text:
        _set_alt_text(graphic_frame, element.alt_text)

    footer_note = _apply_footer(slide, element, "table", metadata, reportifyr_ctx, design)

    source_manifest = {"resolved_path": str(table_path), "sha256": _sha256_file(table_path)}
    return graphic_frame, source_manifest, warnings, footer_note


# ---------------------------------------------------------------------------
# Quarto fragments (spec section 8.1, issue #3)
# ---------------------------------------------------------------------------


def _add_quarto_shape(
    slide: Any,
    element: ResolvedElement,
    quarto_config: QuartoExecutionConfig,
    design: DesignDocument,
    *,
    project_root: Path,
) -> tuple[Any, dict[str, str], list[str], str]:
    """Resolve and place a `quarto` element, returning `(shape,
    source_manifest, warnings, resolved_render_mode)` -- the extra
    `resolved_render_mode` return (vs. every other `_add_*_shape`
    helper) is what `_compose_element` records in the manifest instead
    of `element.render_mode`, since that may be the unresolved `"auto"`
    (spec section 8's render-mode table).

    `render_mode: native` reuses `_add_text_shape` verbatim by building a
    `markdown`-typed copy of `element` carrying the executed fragment's
    Markdown text (`dataclasses.replace`) -- Quarto's own GFM output is
    exactly the Markdown `_add_text_shape` already knows how to parse,
    so there is no second Markdown renderer here. `png` instead reuses
    `_place_picture`, the same picture-placement `image` and
    `reportifyr` elements share. `svg` is rejected here, not upstream in
    `deckifyr.plan`/the schema -- `deckifyr.renderers.quarto` can render
    one just fine, and a future non-PPTX consumer of a resolved plan
    might want it, but `python-pptx` cannot embed one at all (confirmed:
    `pptx.package.py` treats SVG as an unrecognized image type outright,
    and `_place_picture`'s own Pillow-based sizing can't open one
    either) -- see `deckifyr.renderers.quarto`'s module docstring.
    """
    resolver = QuartoResolver(config=quarto_config)
    context = BuildContext(project_root=str(project_root))
    # Same "style if set, else design.yaml's own body font/text color"
    # fallback `_add_text_shape` uses -- so a rasterized fragment's prose
    # matches the surrounding deck's typography by default, not just
    # when an author remembers to set `style:` on the element (see
    # `deckifyr.renderers.quarto._inject_typst_autosize`'s docstring for
    # why this only touches prose, not the fragment's own math).
    style = element.style
    font_name = style.font if style else design.fonts.body
    text_color = style.color if style else design.colors.get("text", "#000000")
    artifact: QuartoArtifact = resolver.resolve(
        str(element.source),
        context,
        requested_render_mode=element.render_mode,
        font=font_name,
        text_color=text_color,
    ).value

    if artifact.render_mode == "native":
        text_element = replace(element, type="markdown", value=artifact.markdown)
        shape = _add_text_shape(slide, text_element, design)
    elif artifact.render_mode == "svg":
        if artifact.image_path is not None:
            artifact.image_path.unlink(missing_ok=True)
        raise ContentValidationError(
            f"element {element.id!r}: render_mode: svg cannot be composed "
            "into a .pptx -- python-pptx has no SVG embedding support "
            "(spec section 8's render-mode table: \"svg: ... limited "
            "editability and support variability\") -- use render_mode: "
            "png (or native/auto) instead"
        )
    else:
        if not element.alt_text:
            raise ContentValidationError(
                f"element {element.id!r}: a 'quarto' element rendered as "
                f"{artifact.render_mode!r} requires alt_text (spec section "
                "13's content validation: \"missing required alt text\")"
            )
        try:
            shape = _place_picture(slide, element, artifact.image_path)
        finally:
            artifact.image_path.unlink(missing_ok=True)

    source_manifest = {"resolved_path": str(artifact.path), "sha256": _sha256_file(artifact.path)}
    return shape, source_manifest, artifact.warnings, artifact.render_mode


# ---------------------------------------------------------------------------
# Compose + write
# ---------------------------------------------------------------------------


def _compose_element(
    slide: Any,
    slide_id: str,
    element: ResolvedElement,
    design: DesignDocument,
    reportifyr_ctx: ReportifyrBuildContext,
    quarto_config: QuartoExecutionConfig,
    *,
    project_root: Path,
) -> tuple[Any, list[dict[str, Any]], list[str], list[str]]:
    """Place one resolved element on `slide` and return `(shape,
    manifest_entries, warnings, footer_notes)`. Recursive for `group`:
    each child is composed the same way, directly on `slide` (group
    children share the slide's own absolute coordinate space -- spec
    section 7.3 -- rather than a group-relative one), then
    `add_group_shape` reparents the already-placed child shapes under a
    new group shape, per python-pptx's own documented pattern for
    building a group from existing shapes.
    """
    source_manifest: dict[str, str] = {}
    manifest_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    footer_notes: list[str] = []
    # Overridden below only for `quarto`, whose manifest `render_mode`/
    # `editability` depend on the *resolved* mode, not the static
    # per-type mapping every other element type uses (see `_EDITABILITY`
    # and `_add_quarto_shape`'s own docstring).
    manifest_render_mode = element.render_mode
    editability = _EDITABILITY[element.type]

    if element.type in ("text", "markdown"):
        shape = _add_text_shape(slide, element, design)
    elif element.type == "image":
        shape, source_manifest = _add_image_shape(slide, element, project_root=project_root)
    elif element.type == "reportifyr":
        shape, source_manifest, elem_warnings, footer_note = _add_reportifyr_shape(
            slide, element, reportifyr_ctx, design, project_root=project_root
        )
        warnings.extend(elem_warnings)
        if footer_note:
            footer_notes.append(footer_note)
    elif element.type == "shape":
        shape = _add_autoshape(slide, element)
    elif element.type == "table":
        shape, source_manifest, elem_warnings, footer_note = _add_table_shape(
            slide, element, design, reportifyr_ctx, project_root=project_root
        )
        warnings.extend(elem_warnings)
        if footer_note:
            footer_notes.append(footer_note)
    elif element.type == "quarto":
        shape, source_manifest, elem_warnings, resolved_render_mode = _add_quarto_shape(
            slide, element, quarto_config, design, project_root=project_root
        )
        warnings.extend(elem_warnings)
        manifest_render_mode = resolved_render_mode
        editability = "fully_editable" if resolved_render_mode == "native" else "rendered_graphic"
    elif element.type == "group":
        child_shapes = []
        for child in element.children:
            child_shape, child_entries, child_warnings, child_footer_notes = _compose_element(
                slide, slide_id, child, design, reportifyr_ctx, quarto_config, project_root=project_root
            )
            child_shapes.append(child_shape)
            manifest_entries.extend(child_entries)
            warnings.extend(child_warnings)
            footer_notes.extend(child_footer_notes)
        shape = slide.shapes.add_group_shape(child_shapes)
        shape.name = element.id
        shape.rotation = element.rotation
        if element.alt_text:
            _set_alt_text(shape, element.alt_text)
    else:  # pragma: no cover -- deckifyr.plan already rejects this
        raise ContentValidationError(
            f"element {element.id!r}: element type {element.type!r} "
            "is not implemented yet"
        )

    manifest_entries.append(
        {
            "slide_id": slide_id,
            "element_id": element.id,
            "type": element.type,
            "render_mode": manifest_render_mode,
            "editability": editability,
            "overflow_policy": element.overflow,
            **source_manifest,
        }
    )
    return shape, manifest_entries, warnings, footer_notes


def compose(
    presentation: PresentationDocument,
    design: DesignDocument,
    resolved_slides: list[ResolvedSlide],
    *,
    project_root: Path,
) -> tuple[PptxPresentation, list[dict[str, Any]], list[str]]:
    prs = PptxPresentation()
    prs.slide_width = Emu(parse_length(design.slide.width, strict=True))
    prs.slide_height = Emu(parse_length(design.slide.height, strict=True))
    blank_layout = _find_blank_layout(prs)

    reportifyr_ctx = _build_reportifyr_context(presentation, design, project_root=project_root)
    quarto_config = _build_quarto_config(presentation)

    element_manifest: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Resolved once per build, not once per slide -- every slide's native
    # background fill is the same `design.slide` token(s).
    background_gradient = (
        resolve_gradient(design, design.slide.background_gradient)
        if design.slide.background_gradient is not None
        else None
    )

    for resolved_slide in resolved_slides:
        slide = prs.slides.add_slide(blank_layout)
        if background_gradient is not None:
            _apply_gradient(slide.background.fill, background_gradient)
        else:
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = _hex_to_rgbcolor(design.slide.background)

        notes_parts = [resolved_slide.notes] if resolved_slide.notes else []

        for element in resolved_slide.elements:
            _shape, entries, elem_warnings, elem_footer_notes = _compose_element(
                slide,
                resolved_slide.id,
                element,
                design,
                reportifyr_ctx,
                quarto_config,
                project_root=project_root,
            )
            element_manifest.extend(entries)
            warnings.extend(elem_warnings)
            notes_parts.extend(elem_footer_notes)

        if notes_parts:
            slide.notes_slide.notes_text_frame.text = "\n\n".join(notes_parts)

    return prs, element_manifest, warnings


def compose_and_write(
    presentation: PresentationDocument,
    design: DesignDocument,
    resolved_slides: list[ResolvedSlide],
    *,
    project_root: Path,
    presentation_path: Path,
    design_path: Path,
    layouts_path: Path,
    force_previews: bool = False,
    preview_slides: list[int] | None = None,
    keep_preview_pdf: bool = False,
) -> BuildResult:
    started_at = datetime.now(timezone.utc)
    prs, element_manifest, warnings = compose(
        presentation, design, resolved_slides, project_root=project_root
    )

    output_path = (project_root / presentation.build.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    ended_at = datetime.now(timezone.utc)

    # `force_previews` is `deckifyr preview`'s own escape hatch (spec
    # section 11.1): an explicit preview request renders regardless of
    # the project's own `build.previews` flag, without requiring an
    # author to permanently flip that flag on just to check one preview.
    # An ordinary `deckifyr build` only renders when `build.previews` is
    # set, per that field's own docstring.
    preview_paths: list[Path] = []
    preview_pdf_path: Path | None = None
    if presentation.build.previews or force_previews:
        preview_result = render_slide_previews(
            output_path,
            output_path.parent / "previews",
            config=_build_preview_config(presentation),
            slides=preview_slides,
            keep_pdf=keep_preview_pdf,
        )
        preview_paths = preview_result.image_paths
        preview_pdf_path = preview_result.pdf_path

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
        "previews": [str(p) for p in preview_paths],
        "preview_pdf": str(preview_pdf_path) if preview_pdf_path else None,
        "warnings": warnings,
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
        warnings=warnings,
        preview_paths=preview_paths,
        preview_pdf_path=preview_pdf_path,
    )
