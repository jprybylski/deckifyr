"""Project-file discovery for the web editor.

`list_reportifyr_artifacts`/`list_quarto_fragments` back the "Add
element" menu (issue #31): listing the `reportifyr`/`quarto` sources a
new element could validly point at, rather than requiring a hand-typed
path -- `deckifyr.web.app`'s `GET /api/project/files` route calls them.
`list_project_directory` backs the Build tab's output-path browser
(issue #32) instead: a single-level (non-recursive) directory listing,
called once per directory an author actually clicks into rather than
walking the whole project tree up front -- `deckifyr.web.app`'s `GET
/api/project/browse` route calls it.

Deliberately its own small module, not a method on `ReportifyrResolver`/
`QuartoResolver` -- those classes resolve one already-known reference
(spec section 9.2's `ContentResolver` contract); every function here is a
different kind of operation (enumerate candidates/entries) with no
resolver-protocol shape of its own.
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


# Combined dirs+files cap for one `list_project_directory` call (issue
# #32's output-path browser). Deliberately small and deliberately not
# configurable: this exists to keep one directory listing response (and
# the DOM it becomes) bounded, not to be a real pagination mechanism --
# a directory with more entries than this is nearly always something
# irrelevant to "where should the built .pptx go" (a populated
# `renv/library/<hash>` cache dir, `node_modules`, ...), and the browser
# UI's own `truncated` note tells the author to type a subdirectory name
# directly instead.
_MAX_BROWSE_ENTRIES = 500


def list_project_directory(
    project_root: Path, rel_dir: str
) -> tuple[list[str], list[str], bool]:
    """One single level (`Path.iterdir()`, never `rglob`) of
    `project_root / rel_dir` -- `(subdirectory names, file names,
    truncated)`, each list sorted and capped at `_MAX_BROWSE_ENTRIES`
    combined.

    Deliberately non-recursive: `deckifyr.web.app`'s `GET
    /api/project/browse` route (issue #32's output-path "file select")
    calls this once per directory the user actually clicks into, not
    once for the whole project tree the way `list_reportifyr_artifacts`/
    `list_quarto_fragments` above eagerly `rglob` theirs -- a project
    with a deep, unrelated directory tree (a populated `renv/library`, a
    `node_modules`, ...) never gets walked or globbed as a whole just
    because an author opened the output-path browser once. The entry cap
    guards the other half of the same concern: even a single directory
    can itself be huge in that kind of tree (a populated
    `renv/library/<hash>` cache directory, say), so this still bounds
    one call's own response/DOM size rather than assuming "one level" is
    automatically small.

    Raises `ContentValidationError` if `rel_dir` resolves outside
    `project_root` (same containment check `list_reportifyr_artifacts`
    uses) or isn't a directory.
    """
    project_root = Path(project_root).resolve()
    target = (project_root / rel_dir).resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise ContentValidationError(
            f"directory {rel_dir!r} resolves outside the project root {project_root}"
        ) from exc
    if not target.is_dir():
        raise ContentValidationError(f"{rel_dir!r} is not a directory")

    dirs: list[str] = []
    files: list[str] = []
    for entry in target.iterdir():
        (dirs if entry.is_dir() else files).append(entry.name)
    dirs.sort()
    files.sort()

    truncated = len(dirs) + len(files) > _MAX_BROWSE_ENTRIES
    if truncated:
        # Directories first, up to the cap, then whatever room is left
        # for files -- matches the browser UI's own dirs-before-files
        # row ordering, so a truncated listing doesn't arbitrarily favor
        # files over the (usually more useful, for navigation purposes)
        # directories.
        dirs = dirs[:_MAX_BROWSE_ENTRIES]
        files = files[: max(0, _MAX_BROWSE_ENTRIES - len(dirs))]
    return dirs, files, truncated
