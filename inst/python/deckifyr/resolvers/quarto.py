"""Quarto fragment resolver (spec section 9.2's "Quarto fragment
resolver", section 8.1, issue #3).

Resolves a `quarto` element's `source` (a project-relative `.qmd` path,
mirroring `LocalFileResolver`'s own path-safety rule) to executed
content -- normalized Markdown text for `render_mode: native`, or a
rasterized `svg`/`png` image path for the other modes -- by delegating
the actual Quarto invocation to `deckifyr.renderers.quarto`. This module
owns path resolution and `render_mode: auto`'s resolved-vs-declared
bookkeeping; `deckifyr.renderers.quarto` owns the subprocess/complexity/
timeout mechanics. Nothing here reuses Quarto's own PPTX writer (spec
section 20 warning 2) -- the resolved content is placed by
`deckifyr.pptx.compose` exactly like an ordinary `markdown`/`image`
element.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from deckifyr.renderers.quarto import (
    QuartoExecutionConfig,
    render_image,
    render_native,
    select_auto_render_mode,
)
from deckifyr.resolvers import BuildContext, ResolvedContent
from deckifyr.schema.errors import ContentValidationError


@dataclass
class QuartoArtifact:
    path: Path
    # The resolved mode actually used -- "native", "svg", or "png",
    # never "auto" (spec section 8's render-mode table: an `auto` choice
    # "must be recorded in the manifest to avoid surprises";
    # `deckifyr.pptx.compose` reads this field for that manifest entry
    # rather than the element's own possibly-`"auto"` `render_mode`).
    render_mode: str
    markdown: str | None = None
    image_path: Path | None = None
    image_format: str | None = None
    warnings: list[str] = field(default_factory=list)


class QuartoResolver:
    def __init__(self, *, config: QuartoExecutionConfig | None = None) -> None:
        self.config = config or QuartoExecutionConfig()

    def supports(self, value: str) -> bool:
        if value.startswith("{rpfy}:"):
            return False
        return value.endswith(".qmd")

    def resolve(
        self,
        value: str,
        context: BuildContext,
        *,
        requested_render_mode: str = "auto",
        font: str | None = None,
        text_color: str | None = None,
    ) -> ResolvedContent:
        """`font`/`text_color` only matter for an `svg`/`png`-resolved
        render -- see `deckifyr.renderers.quarto.render_image`'s own
        docstring for why they're applied to a rasterized fragment's
        prose, not its math.
        """
        project_root = Path(context.project_root).resolve()
        path = (project_root / value).resolve()
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise ContentValidationError(
                f"quarto source {value!r} resolves outside the project root "
                f"{project_root}"
            ) from exc
        if not path.is_file():
            raise ContentValidationError(f"quarto source file not found: {path}")

        resolved_mode = requested_render_mode
        if resolved_mode == "auto":
            resolved_mode = select_auto_render_mode(path.read_text(encoding="utf-8"))

        if resolved_mode == "native":
            markdown = render_native(path, config=self.config)
            artifact = QuartoArtifact(path=path, render_mode="native", markdown=markdown)
        elif resolved_mode in ("svg", "png"):
            image_path = render_image(
                path,
                image_format=resolved_mode,
                config=self.config,
                font=font,
                text_color=text_color,
            )
            artifact = QuartoArtifact(
                path=path,
                render_mode=resolved_mode,
                image_path=image_path,
                image_format=resolved_mode,
            )
        else:
            raise ContentValidationError(
                f"quarto element {value!r}: unsupported render_mode "
                f"{requested_render_mode!r} (expected native, svg, png, or auto)"
            )

        return ResolvedContent(value=artifact)
