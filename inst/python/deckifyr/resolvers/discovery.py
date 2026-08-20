"""Project-file discovery for the web editor's "Add element" menu
(issue #31): listing the `reportifyr`/`quarto` sources a new element
could validly point at, rather than requiring a hand-typed path.

Deliberately its own small module, not a method on `ReportifyrResolver`/
`QuartoResolver` -- those classes resolve one already-known reference
(spec section 9.2's `ContentResolver` contract); this is a different
operation (enumerate every *valid* reference) with no resolver-protocol
shape of its own, and only `deckifyr.web.app`'s new
`GET /api/project/files` route calls it.
"""

from __future__ import annotations

from pathlib import Path

from deckifyr.resolvers.reportifyr import metadata_sidecar_path
from deckifyr.schema.errors import ContentValidationError


def list_reportifyr_artifacts(project_root: Path, outputs_dir: str) -> list[str]:
    """Every artifact filename under `outputs_dir` that would actually
    resolve as a `{rpfy}:<name>` reference -- i.e. has a real
    `<stem>_<ext>_metadata.json` sidecar alongside it
    (`metadata_sidecar_path`'s own naming convention, confirmed against
    reportifyr's `write_object_metadata()`), the same "can validly be
    considered" bar issue #31 itself names. Applies the same project-root
    containment check `_find_artifact` uses, even though `outputs_dir`
    here comes from `build.reportifyr.outputs_dir` (project config, not
    a request-supplied path) -- same hygiene either way.
    """
    search_root = (project_root / outputs_dir).resolve()
    try:
        search_root.relative_to(project_root)
    except ValueError as exc:
        raise ContentValidationError(
            f"reportifyr outputs_dir {outputs_dir!r} resolves outside the "
            f"project root {project_root}"
        ) from exc
    if not search_root.is_dir():
        return []

    names: list[str] = []
    for sidecar in sorted(search_root.rglob("*_metadata.json")):
        # `_metadata_sidecar_path` builds `<stem>_<suffix>_metadata.json`
        # from `<stem>.<suffix>` -- inverting it means splitting off
        # exactly that same `_<suffix>_metadata.json` tail, not just
        # trimming `_metadata.json`, since the artifact's own suffix is
        # embedded in the middle of the sidecar's name.
        name = sidecar.name.removesuffix("_metadata.json")
        stem, _, suffix = name.rpartition("_")
        if not suffix:
            continue
        artifact_path = sidecar.with_name(f"{stem}.{suffix}")
        if artifact_path.is_file() and metadata_sidecar_path(artifact_path) == sidecar:
            names.append(artifact_path.name)
    return sorted(set(names))


def list_quarto_fragments(project_root: Path) -> list[str]:
    """Every `.qmd` file under `project_root`, as project-relative
    POSIX paths (the same form a `quarto` element's own `source` field
    takes) -- reuses no path-safety check of its own since the glob
    root is `project_root` itself, not a caller-supplied path.
    """
    project_root = Path(project_root).resolve()
    return sorted(
        p.relative_to(project_root).as_posix() for p in project_root.rglob("*.qmd") if p.is_file()
    )
