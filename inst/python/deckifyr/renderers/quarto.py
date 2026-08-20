"""Quarto fragment execution (spec section 8/8.1, issue #3).

A `type: quarto` element binds a single `.qmd` fragment to one element's
`box` -- not a whole document, per section 8.1's complexity limit. This
module owns the two things that limit implies: rejecting a fragment that
tries to be more than one fragment (`check_fragment_complexity`), and
actually invoking the real `quarto` binary to turn a fragment into
either normalized text (`render_native`) or a rasterized image
(`render_image`), bounded by an execution timeout and an output-size
limit (`QuartoExecutionConfig`).

Two render paths, matching spec section 8's render-mode table:

- `native` (`--to gfm`): Quarto's own words, "Produce Pandoc AST or
  normalized Markdown for native text conversion" -- the executed
  fragment's Markdown output is handed to
  `deckifyr.pptx.compose._add_text_shape` the same way an ordinary
  `markdown` element's `value` is (reusing that element's own paragraph/
  bold/italic parsing, not a second Markdown renderer). This is real,
  editable PowerPoint text, but it cannot represent display math as
  actual glyphs (`python-pptx` has no OMML equation API) -- an
  equation-heavy fragment belongs in `svg`/`png` mode instead.
- `svg`/`png` (`--to typst`): renders through Quarto's bundled Typst
  toolchain -- chosen over `--to pdf` specifically because it needs no
  separately-installed LaTeX engine (`quarto check` on a machine with no
  TinyTeX still reports Typst as bundled and working), which matters
  since section 15's isolated-execution story shouldn't also require
  provisioning a full LaTeX install. Typst's page defaults to a fixed
  page size (e.g. US Letter) with page-number footers turned on, which
  would rasterize as one small fragment adrift in a mostly-blank page
  with a stray "1" printed under it -- `_inject_typst_autosize` works
  around this by rendering a sibling copy of the fragment with a
  `#set page(width: auto, height: auto, margin: ..., numbering: none,
  fill: none)`
  raw Typst block spliced in after any YAML frontmatter (confirmed
  empirically, twice: the same `#set page` rule passed via Pandoc's
  `--include-in-header` does *not* take effect at all, because Quarto's
  own Typst template evidently re-establishes page defaults after that
  injection point -- splicing it into the document body itself is what
  actually works; and the page-numbering footer specifically was caught
  by rendering a real two-equation fragment end-to-end for
  `examples/demo-deck` and finding a literal "1" baked into the
  resulting PNG, not anticipated from reading Quarto's docs). The
  resulting content-sized PDF's
  first page is then rasterized with PyMuPDF (a pure-Python dependency,
  imported lazily like `pyarrow` in `deckifyr.resolvers.table` --
  chosen specifically to avoid a hard dependency on system-installed
  `poppler-utils`) with `alpha=True` so a `png` render's background stays
  transparent rather than pymupdf's own default of compositing onto
  opaque white (issue #9) -- `fill: none` alone only keeps the *PDF*
  page transparent; without also passing `alpha=True` to `get_pixmap`,
  the rasterizer still flattens that transparency onto white. Both
  formats work at this module's level -- but
  `deckifyr.pptx.compose` (confirmed against a real render, not just
  read from docs: `pptx.package.py` explicitly skips SVG as an
  "unknown/unsupported image type", and Pillow -- which
  `_place_picture`'s fit-mode sizing depends on -- cannot open an SVG
  either) rejects `render_mode: svg` outright rather than silently
  falling back, matching spec section 8's own render-mode table caveat
  ("svg: ... limited editability and support variability"). `png` is
  what an author should actually reach for; `select_auto_render_mode`
  never picks `svg` for exactly this reason.

**Why `png` mode rasterizes an equation instead of embedding a native,
editable PowerPoint equation -- and why that's a real gap, not an
inherent one.** `python-pptx` itself has no API for inserting OMML
(`<m:oMath>`, PowerPoint's native equation markup) -- that part is a
hard limitation of the library this compositor is built on. But Quarto/
Pandoc's own `--to pptx` writer *does* emit real, natively editable
`<m:oMath>` equations: rendering `$$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$$`
through `quarto render x.qmd --to pptx` and inspecting the resulting
slide XML shows a genuine `<a14:m><m:oMathPara><m:oMath>...</m:oMath>
</m:oMathPara></a14:m>` element, not a picture -- confirmed with a real
render, not assumed. So rasterizing to `png` is a deliberate choice
constrained by *this module's* scope, not a technical dead end: a
`native`-equation render mode is possible by pulling the same OMML
Pandoc already knows how to generate (via a full `--to pptx`/`--to docx`
render) out of its slide/document XML and splicing that fragment into
one of this compositor's own text runs -- the same kind of narrow,
tested OOXML adapter `deckifyr.pptx.compose._set_cell_borders`/
`_set_alt_text` already are for other python-pptx gaps. It isn't done
here because that splice needs real OOXML-namespace/content-type wiring
(`a14:`/`m:` namespace declarations, `mc:AlternateContent` fallback
content for viewers that don't understand the extension) verified
against a real PowerPoint install, not just a round-trip through
`python-pptx`/LibreOffice -- a correctness bar this module's existing
adapters were held to (see CLAUDE.md's `_set_cell_borders` note) that
hasn't been cleared here yet. Treat this as a well-scoped, documented
future improvement (deckifyr-specification.md section 21-style open
decision), not something to silently attempt without that same
verification rigor.

Every render happens in an isolated output directory (`--output-dir`,
confirmed to keep Quarto's own `.quarto/` cache and rendered artifacts
out of the project tree entirely) and the sibling fragment `svg`/`png`
mode writes is always cleaned up in a `finally`, per section 15's "one
isolated working directory per job" -- though this is still a local-
trusted-project execution model, not sandboxed/containerized (that
remains a hosted-deployment concern per section 15, not this module's
job).

> **Warning (spec section 8):** Running Quarto executes arbitrary
> project code (R/Python/Julia chunks). This module must never run
> inside an unisolated multi-user web request process.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from deckifyr.schema.errors import ContentValidationError, MissingDependencyError

# Rasterization DPI for `render_mode: png` -- high enough to stay crisp
# at typical slide-figure sizes without ballooning file size.
_PNG_DPI = 200

_QUARTO_INSTALL_URL = "https://quarto.org/docs/get-started/"

_FRONTMATTER_DELIM = "---"
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
_H1_RE = re.compile(r"^#\s+\S")
_CODE_CHUNK_START_RE = re.compile(r"^`{3,}\{(r|python|julia|ojs)\b", re.IGNORECASE)
_DISPLAY_MATH_RE = re.compile(r"\$\$|\\\[")


@dataclass
class QuartoExecutionConfig:
    """Resolved `presentation.yaml` `build.quarto` settings (spec section
    8.1's still-open "exact limit" decision -- these are this slice's
    concrete defaults, project-overridable, not the final word).
    """

    binary: str = "quarto"
    timeout_seconds: float = 60
    max_output_bytes: int = 5_000_000
    # Whitespace pad around a `svg`/`png` render's content-sized Typst
    # page (see this module's docstring) -- small on purpose, since the
    # element's own `box`, not the fragment, is what actually places it
    # on the slide.
    image_margin_in: float = 0.15


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a `.qmd`'s optional leading YAML frontmatter (delimited by a
    `---` line at position 0 and the next standalone `---` line) from the
    rest of the document. Returns `(frontmatter_block, body)`;
    `frontmatter_block` is `""` when there is none. Both halves keep
    their own newlines so the caller can losslessly reassemble them.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return "", text
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIM:
            return "".join(lines[: index + 1]), "".join(lines[index + 1 :])
    return "", text


def _body_lines_outside_fences(body: str):
    """Yield body lines that aren't inside a fenced code block, so
    complexity scanning doesn't mistake code contents (which may
    legitimately contain `#`-prefixed comments or `---`-shaped output)
    for Markdown structure. Crude fence matching (same opening/closing
    character, length ignored past the first three) -- good enough to
    avoid false positives on ordinary fragments, not a full CommonMark
    fence parser.
    """
    fence_char: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if fence_char is not None:
            if stripped.startswith(fence_char * 3):
                fence_char = None
            continue
        match = _FENCE_RE.match(stripped)
        if match:
            fence_char = match.group(1)[0]
            continue
        yield line


def check_fragment_complexity(source_text: str, *, label: str) -> None:
    """Reject a `.qmd` source that tries to be more than one Deckifyr
    element's worth of content (spec section 8.1's complexity limit).

    Two heuristic signals, checked outside fenced code and the YAML
    frontmatter: a Markdown horizontal-rule-shaped line (`---`/`***`/
    `___`, the Reveal/PowerPoint slide-break convention section 8.1 calls
    out) and more than one top-level (`#`) heading. Both are heuristics,
    not a full document-structure parse -- a setext-style heading
    (`Title\\n-----`) can false-positive on the first check; section
    8.1 itself frames the exact limit as still open, so ATX (`#`/`##`)
    headings are the documented, unambiguous way to write a fragment's
    heading instead.
    """
    _, body = _split_frontmatter(source_text)
    heading_count = 0
    for line in _body_lines_outside_fences(body):
        stripped = line.strip()
        if not stripped:
            continue
        if _HR_RE.match(stripped):
            raise ContentValidationError(
                f"{label}: a 'quarto' element's .qmd source must be a single "
                "fragment bound to one element's box, not a multi-section "
                "document (spec section 8.1) -- found a slide/section break "
                f"({stripped!r})"
            )
        if _H1_RE.match(stripped):
            heading_count += 1
            if heading_count > 1:
                raise ContentValidationError(
                    f"{label}: a 'quarto' element's .qmd source must be a "
                    "single fragment (spec section 8.1) -- found more than "
                    "one top-level ('#') heading"
                )


def select_auto_render_mode(source_text: str) -> str:
    """`render_mode: auto`'s content-type heuristic (spec section 8's
    render-mode table: "auto: Convenient defaults by content type").
    Picks `png` when the fragment either executes code (an R/Python/
    Julia/Observable chunk -- the kind of content most likely to produce
    a plot or a table Quarto renders far better than this module's
    hand-rolled Markdown-to-PPTX-text path) or contains display math
    (`$$.../\\[...\\]` -- `python-pptx` has no OMML equation API, so real
    glyphs only come from the rasterized path); otherwise `native`. Never
    resolves to `svg` -- see this module's own docstring for why
    `deckifyr.pptx.compose` can't embed one. The caller
    (`QuartoResolver.resolve`) is responsible for recording the
    *resolved* mode in the build manifest, not the literal `"auto"` --
    spec section 8's own table: "Must be recorded in the manifest to
    avoid surprises."
    """
    _, body = _split_frontmatter(source_text)
    fence_char: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if fence_char is not None:
            if stripped.startswith(fence_char * 3):
                fence_char = None
            continue
        match = _FENCE_RE.match(stripped)
        if match:
            if _CODE_CHUNK_START_RE.match(stripped):
                return "png"
            fence_char = match.group(1)[0]
            continue
        if _DISPLAY_MATH_RE.search(stripped):
            return "png"
    return "native"


def _require_quarto(config: QuartoExecutionConfig) -> None:
    if shutil.which(config.binary) is None:
        raise MissingDependencyError(
            f"quarto binary {config.binary!r} was not found on PATH -- "
            f"install Quarto ({_QUARTO_INSTALL_URL}) to build a "
            "presentation containing 'quarto' elements, or set "
            "build.quarto.binary to its full path",
            name="quarto",
            display_name="Quarto",
            install_url=_QUARTO_INSTALL_URL,
        )


def _check_size(data: bytes, config: QuartoExecutionConfig, *, label: str) -> None:
    if len(data) > config.max_output_bytes:
        raise ContentValidationError(
            f"{label}: quarto render output ({len(data)} bytes) exceeds the "
            f"configured limit of {config.max_output_bytes} bytes "
            "(build.quarto.max_output_bytes)"
        )


def _run_quarto(
    cmd: list[str], *, cwd: Path, config: QuartoExecutionConfig, label: str
) -> None:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=config.timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        raise ContentValidationError(
            f"{label}: quarto render exceeded its {config.timeout_seconds}s "
            "execution timeout (build.quarto.timeout_seconds)"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ContentValidationError(f"{label}: quarto render failed:\n{detail}")


def render_native(qmd_path: Path, *, config: QuartoExecutionConfig) -> str:
    """Execute `qmd_path` and return its rendered GitHub-Flavored-Markdown
    text (`--to gfm`), for `render_mode: native` (this module's
    docstring). Raises `ContentValidationError` for a fragment that fails
    the complexity limit, times out, exceeds the output-size limit, or
    whose render otherwise fails.

    `--wrap none` is passed through to Pandoc (confirmed empirically,
    against a real render of a genuinely long paragraph -- not assumed):
    without it, Pandoc's `gfm` writer hard-wraps prose at its own default
    column width, inserting single `\\n` line breaks mid-paragraph.
    `deckifyr.pptx.compose._add_text_shape`'s `_markdown_paragraphs`
    splits on every non-blank line, one paragraph per line (matching how
    every other `markdown` element's `value` in this codebase is
    authored -- one full line per paragraph in the YAML source) --
    without `--wrap none`, a single wrapped Quarto-rendered paragraph
    would come out as several short, prematurely-broken paragraphs
    instead of one.
    """
    source_text = qmd_path.read_text(encoding="utf-8")
    check_fragment_complexity(source_text, label=str(qmd_path))
    _require_quarto(config)

    with tempfile.TemporaryDirectory(prefix="deckifyr-quarto-") as tmp:
        out_dir = Path(tmp)
        _run_quarto(
            [
                config.binary,
                "render",
                str(qmd_path),
                "--to",
                "gfm",
                "--output-dir",
                str(out_dir),
                "--wrap",
                "none",
            ],
            cwd=qmd_path.parent,
            config=config,
            label=str(qmd_path),
        )
        output_path = out_dir / f"{qmd_path.stem}.md"
        if not output_path.is_file():
            raise ContentValidationError(
                f"{qmd_path}: quarto render did not produce the expected "
                f"output {output_path.name}"
            )
        data = output_path.read_bytes()
        _check_size(data, config, label=str(qmd_path))
        return data.decode("utf-8").strip()


def _typst_string_literal(value: str) -> str:
    """Escape a plain string for interpolation into a raw Typst
    `#set ...(...)` call injected below -- font names and hex colors are
    project config (`design.yaml` tokens), not untrusted input, but this
    keeps a stray `"` in one from breaking the generated Typst source
    rather than silently producing a mis-rendered (or unrenderable)
    fragment.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _inject_typst_autosize(
    source_text: str,
    *,
    config: QuartoExecutionConfig,
    font: str | None,
    text_color: str | None,
) -> str:
    """Splice the same content-autosizing `#set page(...)` this module's
    docstring describes, plus (new) a `#set text(font: ..., fill: ...)`
    matching the placing element's resolved style (`deckifyr.pptx.compose
    ._add_quarto_shape` passes `element.style`'s font/color, falling back
    to `design.yaml`'s own `fonts.body`/`colors.text` the same way
    `_add_text_shape` does for an ordinary `text`/`markdown` element) --
    without this, a rasterized fragment's prose renders in Typst's own
    default serif font regardless of the surrounding deck's typography,
    which reads as visibly inconsistent with every other (real, native)
    text element on the same slide (confirmed against a real render of
    `examples/demo-deck`'s equation fragment, sitting right next to
    Arial-set native text). This deliberately does *not* touch
    `math.equation`'s own font -- Typst's math mode needs a font with a
    real math table (glyph variants, spacing metrics) that an ordinary
    UI typeface like Arial doesn't have; forcing one there would make
    the rendered math look worse, not more consistent (confirmed against
    a real render: `#set text(font: ...)` alone already leaves
    equations in Typst's own math font while retypesetting only the
    surrounding prose, which is the desired outcome, not a gap).
    """
    frontmatter, body = _split_frontmatter(source_text)
    typst_lines = [
        "#set page(width: auto, height: auto, "
        f"margin: {config.image_margin_in}in, numbering: none, fill: none)"
    ]
    text_args = []
    if font:
        text_args.append(f"font: {_typst_string_literal(font)}")
    if text_color:
        text_args.append(f"fill: rgb({_typst_string_literal(text_color)})")
    if text_args:
        typst_lines.append(f"#set text({', '.join(text_args)})")
    autosize_block = "\n\n```{=typst}\n" + "\n".join(typst_lines) + "\n```\n\n"
    return frontmatter + autosize_block + body


def _rasterize_pdf(pdf_path: Path, image_path: Path, *, image_format: str) -> None:
    try:
        import pymupdf
    except ImportError as exc:
        raise ContentValidationError(
            "rendering a 'quarto' element as svg/png requires the optional "
            "'pymupdf' package (not installed) -- install deckifyr's "
            "'quarto' extra to render quarto elements as images"
        ) from exc

    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc[0]
        if image_format == "svg":
            image_path.write_text(page.get_svg_image(), encoding="utf-8")
        else:
            # alpha=True keeps the page's `fill: none` (set by
            # `_inject_typst_autosize`) transparent in the rasterized PNG,
            # instead of pymupdf's own default of compositing onto opaque
            # white (issue #9) -- a fragment placed over a colored slide
            # background or another element previously showed a visible
            # white box around its content.
            page.get_pixmap(dpi=_PNG_DPI, alpha=True).save(str(image_path))
    finally:
        doc.close()


def render_image(
    qmd_path: Path,
    *,
    image_format: str,
    config: QuartoExecutionConfig,
    font: str | None = None,
    text_color: str | None = None,
) -> Path:
    """Execute `qmd_path` through Quarto's Typst format and rasterize the
    resulting content-sized PDF page to `image_format` (`"svg"` or
    `"png"`), for `render_mode: svg`/`"png"` (this module's docstring).
    Returns a path to a standalone temp file the caller owns and must
    delete once done with it (mirrors `deckifyr.resolvers.reportifyr`'s
    resolved-path contract: the resolver hands back a path, not bytes).

    `font`/`text_color` (a font family name and a `#RRGGBB` hex string)
    are optional style hints applied to the fragment's prose, not its
    math -- see `_inject_typst_autosize`'s own docstring for why.
    """
    source_text = qmd_path.read_text(encoding="utf-8")
    check_fragment_complexity(source_text, label=str(qmd_path))
    _require_quarto(config)

    injected_text = _inject_typst_autosize(
        source_text, config=config, font=font, text_color=text_color
    )
    sibling_path = qmd_path.with_name(f".deckifyr-quarto-{uuid4().hex}.qmd")
    sibling_path.write_text(injected_text, encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="deckifyr-quarto-") as tmp:
            out_dir = Path(tmp)
            _run_quarto(
                [config.binary, "render", str(sibling_path), "--to", "typst", "--output-dir", str(out_dir)],
                cwd=qmd_path.parent,
                config=config,
                label=str(qmd_path),
            )
            pdf_path = out_dir / f"{sibling_path.stem}.pdf"
            if not pdf_path.is_file():
                raise ContentValidationError(
                    f"{qmd_path}: quarto render did not produce the expected "
                    "PDF output"
                )
            _check_size(pdf_path.read_bytes(), config, label=str(qmd_path))

            image_fd, image_name = tempfile.mkstemp(
                prefix="deckifyr-quarto-", suffix=f".{image_format}"
            )
            os.close(image_fd)
            image_path = Path(image_name)
            _rasterize_pdf(pdf_path, image_path, image_format=image_format)
            _check_size(image_path.read_bytes(), config, label=str(qmd_path))
            return image_path
    finally:
        sibling_path.unlink(missing_ok=True)
