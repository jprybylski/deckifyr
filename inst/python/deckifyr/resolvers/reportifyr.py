"""Reportifyr magic-string resolver (spec section 9.1/9.2).

Resolves `{rpfy}:name.ext` (and, partially, `{rpfy}:[a.ext, b.ext]` --
see `_select_entry`) against a project's reportifyr output directory and
its `<name>_<ext>_metadata.json` sidecar, and builds plain footer text
from that sidecar plus the project's `standard_footnotes.yaml`.

This is an independent reimplementation against reportifyr's real,
documented *data* contract -- the magic-string grammar (confirmed by
reading reportifyr's bundled Python engine, `reportipyr/magic.py`), the
metadata JSON sidecar schema (produced by reportifyr's exported R
function `write_object_metadata()`), and the `standard_footnotes.yaml`
schema (spec section 9.1) -- not a port of reportifyr's own footnote
*formatting*. That formatting (config-driven line order, `[...]`
wrapping, Word-specific rendering knobs) lives only in `reportipyr`,
which declares no exported Python API (`__all__ = []`) and has no
docx-free, text-returning function to call instead; deckifyr's own
`build_footer_lines` below is a plain, PPTX-native format built directly
from the sidecar's fields, not a reproduction of that internal
algorithm. See `deckifyr.resolvers`'s own module docstring and spec
section 9.1's "Deckifyr should not reuse Reportifyr's DOCX manipulation
layer."
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from deckifyr.resolvers import BuildContext, ResolvedContent
from deckifyr.schema.errors import ContentValidationError

MAGIC_PREFIX = "{rpfy}:"


@dataclass
class ReportifyrArtifact:
    path: Path
    metadata: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)


def parse_magic_entries(value: str) -> list[str]:
    """Parse a `{rpfy}:` magic string into its artifact filename(s), per
    reportifyr's own grammar (`reportipyr/magic.py`'s
    `parse_magic_entries`, confirmed by reading its bundled source): a
    single filename, or a `[a, b, ...]` bracketed list, each entry
    optionally followed by `<key: value, ...>` args. Those args are
    parsed here only to stay parse-compatible (so a comma inside `<...>`
    doesn't split a bracketed list wrong) and then discarded -- deckifyr
    already has explicit `box`/`fit`/`style` element fields for what
    those args would otherwise control.
    """
    if not value.startswith(MAGIC_PREFIX):
        raise ContentValidationError(f"not a {MAGIC_PREFIX!r} magic string: {value!r}")
    magic_value = value[len(MAGIC_PREFIX) :].strip()

    if magic_value.startswith("[") and magic_value.endswith("]"):
        content = magic_value[1:-1].strip()
        entries: list[str] = []
        current: list[str] = []
        depth = 0
        for ch in content:
            if ch == "<":
                depth += 1
            elif ch == ">" and depth > 0:
                depth -= 1
            if ch == "," and depth == 0:
                entry = "".join(current).strip()
                if entry:
                    entries.append(entry)
                current = []
                continue
            current.append(ch)
        tail = "".join(current).strip()
        if tail:
            entries.append(tail)
    else:
        entries = [magic_value]

    names: list[str] = []
    for entry in entries:
        name = entry.split("<", 1)[0].strip()
        if name:
            names.append(name)
    if not names:
        raise ContentValidationError(f"empty {MAGIC_PREFIX!r} magic string: {value!r}")
    return names


def _select_entry(names: list[str]) -> tuple[str, list[str]]:
    """Multi-figure `{rpfy}:[a, b]` uses only the first entry in this
    slice, per spec section 21's still-open decision -- basic tiling of
    an arbitrary number of figures into one element's box is its own
    layout design question, deferred rather than guessed at. Returns
    `(chosen_name, warnings)` -- the extra entries are recorded as a
    build warning (spec section 14's manifest `warnings`), not silently
    dropped (spec section 20 warning 7).
    """
    if len(names) == 1:
        return names[0], []
    ignored = names[1:]
    warning = (
        f"{MAGIC_PREFIX}[{', '.join(names)}]: multi-figure references are not "
        f"tiled in this version -- using {names[0]!r} and ignoring {ignored!r}"
    )
    return names[0], [warning]


def _find_artifact(project_root: Path, outputs_dir: str, name: str) -> Path:
    search_root = (project_root / outputs_dir).resolve()
    try:
        search_root.relative_to(project_root)
    except ValueError as exc:
        raise ContentValidationError(
            f"reportifyr outputs_dir {outputs_dir!r} resolves outside the "
            f"project root {project_root}"
        ) from exc
    if not search_root.is_dir():
        raise ContentValidationError(f"reportifyr outputs directory not found: {search_root}")

    matches = sorted(p for p in search_root.rglob(name) if p.is_file())
    if not matches:
        raise ContentValidationError(
            f"{MAGIC_PREFIX}{name}: artifact not found under {search_root}"
        )
    if len(matches) > 1:
        raise ContentValidationError(
            f"{MAGIC_PREFIX}{name}: duplicate artifact -- found at "
            f"{[str(m) for m in matches]}"
        )
    return matches[0]


def _metadata_sidecar_path(artifact_path: Path) -> Path:
    """Reportifyr's own sidecar naming convention, confirmed in
    `write_object_metadata.R` and `reportipyr/footnotes.py::load_metadata`:
    `<name>_<ext>_metadata.json` alongside the artifact.
    """
    suffix = artifact_path.suffix.lstrip(".")
    return artifact_path.with_name(f"{artifact_path.stem}_{suffix}_metadata.json")


def _load_metadata(
    artifact_path: Path, *, fail_on_missing: bool
) -> tuple[dict[str, Any] | None, list[str]]:
    sidecar = _metadata_sidecar_path(artifact_path)
    if not sidecar.is_file():
        if fail_on_missing:
            raise ContentValidationError(
                f"{artifact_path}: no reportifyr metadata sidecar found at "
                f"{sidecar} (spec section 9.1) -- set "
                "build.reportifyr.fail_on_missing_metadata: false to build "
                "without one"
            )
        return None, [f"{artifact_path}: no reportifyr metadata sidecar found at {sidecar}; footer skipped"]

    try:
        metadata = json.loads(sidecar.read_text())
    except json.JSONDecodeError as exc:
        if fail_on_missing:
            raise ContentValidationError(f"{sidecar}: invalid JSON metadata sidecar: {exc}") from exc
        return None, [f"{sidecar}: invalid JSON metadata sidecar ({exc}); footer skipped"]

    return metadata, []


class ReportifyrResolver:
    def __init__(self, *, outputs_dir: str = "OUTPUTS", fail_on_missing_metadata: bool = True) -> None:
        self.outputs_dir = outputs_dir
        self.fail_on_missing_metadata = fail_on_missing_metadata

    def supports(self, value: str) -> bool:
        return value.startswith(MAGIC_PREFIX)

    def resolve(self, value: str, context: BuildContext) -> ResolvedContent:
        names = parse_magic_entries(value)
        name, warnings = _select_entry(names)

        project_root = Path(context.project_root).resolve()
        path = _find_artifact(project_root, self.outputs_dir, name)
        metadata, meta_warnings = _load_metadata(
            path, fail_on_missing=self.fail_on_missing_metadata
        )
        warnings.extend(meta_warnings)

        return ResolvedContent(value=ReportifyrArtifact(path=path, metadata=metadata, warnings=warnings))


# ---------------------------------------------------------------------------
# Footer text
# ---------------------------------------------------------------------------


def load_standard_footnotes(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        raise ContentValidationError(f"standard_footnotes.yaml not found: {path}")
    data = yaml.safe_load(path.read_text())
    return data or {}


def _format_notes(
    meta_type: str | None,
    extra_notes: list[str],
    footnotes_section: dict[str, str] | None,
    footnotes_key: str,
) -> str | None:
    parts: list[str] = []
    if meta_type and meta_type != "NA":
        section = footnotes_section or {}
        if meta_type not in section:
            raise ContentValidationError(
                f"meta_type {meta_type!r} not found in {footnotes_key!r} section "
                "of the project's standard_footnotes.yaml"
            )
        text = section[meta_type]
        if text:
            parts.append(text if text.endswith(".") else f"{text}.")
    for note in extra_notes or []:
        parts.append(note if note.endswith(".") else f"{note}.")
    return " ".join(parts) if parts else None


def _format_abbreviations(
    abbrevs: list[str], abbreviations_section: dict[str, str] | None
) -> str | None:
    if not abbrevs:
        return None
    section = abbreviations_section or {}
    formatted = []
    for abbrev in abbrevs:
        if abbrev not in section:
            raise ContentValidationError(
                f"abbreviation {abbrev!r} not found in the project's "
                "standard_footnotes.yaml 'abbreviations' section"
            )
        formatted.append(f"{abbrev}: {section[abbrev].rstrip('.')}")
    return ", ".join(formatted) + "."


def build_footer_lines(
    metadata: dict[str, Any], artifact_type: str, standard_footnotes: dict[str, Any]
) -> list[str]:
    """Build plain footer text lines from a reportifyr metadata sidecar
    and the project's `standard_footnotes.yaml` -- deckifyr's own
    PPTX-native footer format (`Source`/`Notes`/`Abbreviations`), not a
    reimplementation of `reportipyr`'s private, config-driven Word-
    footnote formatting (see this module's docstring).
    """
    if artifact_type not in ("figure", "table"):
        raise ValueError(f"artifact_type must be 'figure' or 'table', got {artifact_type!r}")

    object_meta = metadata.get("object_meta", {})
    source_meta = metadata.get("source_meta") or {}

    lines: list[str] = []

    path = source_meta.get("path")
    if path:
        latest_time = source_meta.get("latest_time")
        source_text = f"{path} {latest_time}" if latest_time else path
        lines.append(f"Source: {source_text}")

    footnotes_key = f"{artifact_type}_footnotes"
    footnotes = object_meta.get("footnotes", {})
    notes_text = _format_notes(
        object_meta.get("meta_type"),
        footnotes.get("notes", []),
        standard_footnotes.get(footnotes_key),
        footnotes_key,
    )
    if notes_text:
        lines.append(f"Notes: {notes_text}")

    abbrev_text = _format_abbreviations(
        footnotes.get("abbreviations", []), standard_footnotes.get("abbreviations")
    )
    if abbrev_text:
        lines.append(f"Abbreviations: {abbrev_text}")

    return lines


# ---------------------------------------------------------------------------
# Subscript/superscript notation
# ---------------------------------------------------------------------------

_SUB_SUP_PATTERN = re.compile(r"(_\{[^}]*\}|\^\{[^}]*\})")


@dataclass
class TextSegment:
    text: str
    script: Literal["normal", "sub", "sup"] = "normal"


def split_scripts(text: str) -> list[TextSegment]:
    """Split `_{...}`/`^{...}` notation into plain/subscript/superscript
    segments. This is how `standard_footnotes.yaml`'s own abbreviation
    keys are written (e.g. `"AUC_{0-24}"`) -- a property of that YAML
    content itself, independent of which tool renders it -- so
    `deckifyr.pptx.compose` can render real subscript/superscript runs
    instead of leaving literal underscores/braces in the footer (spec
    section 20 warning 7: don't silently degrade content).
    """
    if "_{" not in text and "^{" not in text:
        return [TextSegment(text)]

    segments: list[TextSegment] = []
    for part in _SUB_SUP_PATTERN.split(text):
        if not part:
            continue
        if part.startswith("_{") and part.endswith("}"):
            segments.append(TextSegment(part[2:-1], "sub"))
        elif part.startswith("^{") and part.endswith("}"):
            segments.append(TextSegment(part[2:-1], "sup"))
        else:
            segments.append(TextSegment(part))
    return segments
