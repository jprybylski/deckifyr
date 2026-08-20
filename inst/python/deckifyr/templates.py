"""Template-based `init` (spec-adjacent feature, issue #34): scaffold a
new project from a local directory or a git repo instead of only the
bundled `inst/examples/minimal-deck/` fixture.

Mechanism only -- `deckifyr.cli`'s `_cmd_init` owns argument validation
and orchestration, the same "mechanism in its own module, orchestration
in cli.py" split `deckifyr.plan`/`deckifyr.editor`/`deckifyr.projectio`
already established.

Two source shapes:

- **Flat**: a source directory with a root `presentation.yaml`. Its own
  `design.base`/`layouts` fields (read directly, never assumed to be
  literally named `design.yaml`/`layouts.yaml`) name the two files that
  get copied under their original filenames; a *new* minimal
  `presentation.yaml` (`slides: []`, confirmed schema-valid -- no
  min-length constraint on `PresentationDocument.slides`) is generated
  pointing at them. This is the "duplicate a prior project's design"
  case from the issue.
- **Typed**: a source directory with a `templates/` subdirectory, each
  entry a named flat-shaped template of its own. `--type NAME` selects
  one; unlike the flat case, its `presentation.yaml` is copied verbatim
  (it's meant to be a real, minimal starter for that presentation kind,
  not emptied).

Git access (`fetch_git_template`) shells out to a real `git` binary
(`git clone` + `git checkout <ref>`) rather than adding a new HTTP
client dependency -- the same "shell out to an already-trusted external
tool, raise `MissingDependencyError` if it's not on PATH" posture
`deckifyr.renderers.preview` (LibreOffice) and `deckifyr.renderers.quarto`
(Quarto) already establish. A full, non-shallow clone is used
deliberately: template repos are small config repos, and a full clone
sidesteps any shallow-clone limitation on checking out an arbitrary
commit SHA (as opposed to a branch/tag ref a shallow fetch can target
directly).

`resolve_repo_spec`'s `[host/]owner/repo[/subdir][@ref]` shorthand is
the first host-qualified, remotes/pak-style ref grammar in the "fyr
ecosystem" (deckifyr's sibling `quartifyr` has no prior art for this at
all, confirmed by research before writing this module) -- GitHub
Enterprise support falls out for free from the optional host segment,
disambiguated from a bare `owner/repo` by requiring the first segment
to look like a real hostname (contains a `.`, or is `localhost`) rather
than by position alone, since real GitHub owner names essentially never
contain a dot. A full URL (containing `"://"`) is accepted verbatim
instead, for any git host including ones this shorthand can't express
(the `ref`/`subdir` come only from the separate `--ref`/`--subdir`
flags in that form, since they can't be embedded unambiguously in an
arbitrary URL). Explicit `--ref`/`--subdir` flags always win over an
embedded `@ref`/`/subdir` in the shorthand form. A bare local
filesystem path is deliberately not a third accepted `--from-repo`
form -- it would be ambiguous with the shorthand grammar (an absolute
path's segments look exactly like `owner/repo/subdir`), and
`--from-dir` already exists for local directories; a local git
checkout can still be cloned through `--from-repo` by spelling it as a
`file://` URL, which correctly takes the full-URL branch.

v1 deliberately copies only the design/layouts (and, for a typed
source, presentation) YAML files -- never the local assets they
reference (a background image, `standard_footnotes.yaml`, fonts).
`_scan_asset_warnings` reports what it finds instead of trying to
resolve and copy it, the same "well-scoped, documented gap" posture the
Quarto SVG/native-equation limitations already established elsewhere in
this codebase.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import ValidationError as PydanticValidationError

from deckifyr import projectio
from deckifyr.schema.errors import DeckifyrError, ErrorCode, MissingDependencyError
from deckifyr.schema.presentation import PresentationDocument
from deckifyr.schema.version import CURRENT_SCHEMA_VERSION

GIT_INSTALL_URL = "https://git-scm.com/downloads"
DEFAULT_GIT_HOST = "github.com"

_HOST_LIKE_RE = re.compile(r"^(localhost(:\d+)?|[^/]+\.[^/]+)$")


# --- Repo-spec parsing (remotes/pak-style shorthand) ---------------------


@dataclass
class GitSource:
    clone_url: str
    ref: str | None
    subdir: str | None


def resolve_repo_spec(
    spec: str, *, ref: str | None = None, subdir: str | None = None
) -> GitSource:
    """Parse `--from-repo`'s `spec` into a clone URL + ref + subdir.

    Two forms:

    - A full URL (contains `"://"`): passed through verbatim as the
      clone URL. `ref`/`subdir` come only from the `ref`/`subdir`
      keyword arguments (this repo's own `--ref`/`--subdir` flags) --
      nothing is parsed out of the URL itself.
    - Shorthand: `[host/]owner/repo[/subdir][@ref]`. `host` defaults to
      `DEFAULT_GIT_HOST` (github.com); an explicit host segment is
      recognized only when it looks like a real hostname (contains a
      `.`, or is `localhost` with an optional `:port`) -- otherwise the
      first segment is `owner`. Explicit `ref`/`subdir` keyword
      arguments override anything embedded in the shorthand string.
    """
    if "://" in spec:
        return GitSource(clone_url=spec, ref=ref, subdir=subdir)

    remainder, _, embedded_ref = spec.partition("@")
    if not embedded_ref:
        remainder = spec

    segments = [s for s in remainder.split("/") if s]
    if not segments:
        raise DeckifyrError(f"invalid --from-repo spec: {spec!r}", code=ErrorCode.IO)

    host = DEFAULT_GIT_HOST
    if len(segments) >= 3 and _HOST_LIKE_RE.match(segments[0]):
        host = segments[0]
        segments = segments[1:]

    if len(segments) < 2:
        raise DeckifyrError(
            f"invalid --from-repo spec: {spec!r} "
            "(expected '[host/]owner/repo[/subdir][@ref]')",
            code=ErrorCode.IO,
        )

    owner, repo = segments[0], segments[1]
    embedded_subdir = "/".join(segments[2:]) or None

    return GitSource(
        clone_url=f"https://{host}/{owner}/{repo}.git",
        ref=ref if ref is not None else (embedded_ref or None),
        subdir=subdir if subdir is not None else embedded_subdir,
    )


# --- Git fetch -------------------------------------------------------------


def _require_git() -> None:
    if shutil.which("git") is None:
        raise MissingDependencyError(
            "the 'git' binary was not found on PATH -- install Git "
            f"({GIT_INSTALL_URL}) to use --from-repo",
            name="git",
            display_name="Git",
            install_url=GIT_INSTALL_URL,
        )


def _run_git(args: list[str], *, cwd: Path | None = None) -> None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeckifyrError(
            f"git {' '.join(args)} timed out", code=ErrorCode.IO
        ) from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DeckifyrError(
            f"git {' '.join(args)} failed: {detail}", code=ErrorCode.IO
        )


@contextmanager
def fetch_git_template(
    clone_url: str, *, ref: str | None, subdir: str | None
) -> Iterator[Path]:
    """Clone `clone_url` to a temp dir, check out `ref` if given, and
    yield the resolved source directory (the clone root, or its
    `subdir`). The temp dir is removed on exit -- callers must copy
    anything they need out of the yielded path before the `with` block
    ends.
    """
    _require_git()
    with tempfile.TemporaryDirectory(prefix="deckifyr-template-") as tmp:
        repo_dir = Path(tmp) / "repo"
        _run_git(["clone", clone_url, str(repo_dir)])
        if ref:
            _run_git(["checkout", ref], cwd=repo_dir)

        source_dir = repo_dir / subdir if subdir else repo_dir
        if not source_dir.is_dir():
            raise DeckifyrError(
                f"--subdir {subdir!r} not found in {clone_url}", code=ErrorCode.IO
            )
        yield source_dir


# --- Structure detection ---------------------------------------------------


@dataclass
class ResolvedTemplate:
    kind: Literal["flat", "typed"]
    presentation_path: Path
    design_path: Path
    design_filename: str
    layouts_path: Path
    layouts_filename: str


def _read_design_layouts_filenames(presentation_path: Path) -> tuple[str, str]:
    data = projectio.read_yaml(presentation_path)
    if not isinstance(data, dict):
        raise DeckifyrError(
            f"{presentation_path}: expected a mapping at the document root",
            code=ErrorCode.IO,
        )
    try:
        design_filename = data["design"]["base"]
        layouts_filename = data["layouts"]
    except (KeyError, TypeError) as exc:
        raise DeckifyrError(
            f"{presentation_path}: missing design.base/layouts", code=ErrorCode.IO
        ) from exc
    return design_filename, layouts_filename


def _resolve_flat(presentation_path: Path) -> ResolvedTemplate:
    design_filename, layouts_filename = _read_design_layouts_filenames(presentation_path)
    base_dir = presentation_path.parent
    return ResolvedTemplate(
        kind="flat",
        presentation_path=presentation_path,
        design_path=base_dir / design_filename,
        design_filename=design_filename,
        layouts_path=base_dir / layouts_filename,
        layouts_filename=layouts_filename,
    )


def _resolve_typed(templates_dir: Path, type_name: str | None) -> ResolvedTemplate:
    available = sorted(p.name for p in templates_dir.iterdir() if p.is_dir())
    if type_name is None:
        raise DeckifyrError(
            "this source has a templates/ directory -- pass --type to "
            f"select one of: {', '.join(available) or '(none found)'}",
            code=ErrorCode.IO,
        )
    type_dir = templates_dir / type_name
    if type_name not in available or not type_dir.is_dir():
        raise DeckifyrError(
            f"unknown --type {type_name!r} -- available: {', '.join(available) or '(none found)'}",
            code=ErrorCode.IO,
        )

    presentation_path = type_dir / "presentation.yaml"
    resolved = _resolve_flat(presentation_path)
    return ResolvedTemplate(
        kind="typed",
        presentation_path=resolved.presentation_path,
        design_path=resolved.design_path,
        design_filename=resolved.design_filename,
        layouts_path=resolved.layouts_path,
        layouts_filename=resolved.layouts_filename,
    )


def detect_template(source_dir: Path, *, type_name: str | None) -> ResolvedTemplate:
    templates_dir = source_dir / "templates"
    if templates_dir.is_dir():
        return _resolve_typed(templates_dir, type_name)

    presentation_path = source_dir / "presentation.yaml"
    if presentation_path.is_file():
        if type_name is not None:
            raise DeckifyrError(
                f"--type {type_name!r} given, but {source_dir} has no "
                "templates/ directory (it's a flat template source)",
                code=ErrorCode.IO,
            )
        return _resolve_flat(presentation_path)

    raise DeckifyrError(
        f"{source_dir} is not a recognizable deckifyr template source "
        "(expected a presentation.yaml or a templates/<type>/ directory)",
        code=ErrorCode.IO,
    )


# --- Materialization ---------------------------------------------------


def _build_minimal_presentation(target: Path, resolved: ResolvedTemplate) -> dict[str, Any]:
    name = target.resolve().name
    title = name.replace("-", " ").replace("_", " ").title() or "New Presentation"
    return {
        "deckifyr": CURRENT_SCHEMA_VERSION,
        "design": {"base": resolved.design_filename},
        "layouts": resolved.layouts_filename,
        "metadata": {"title": title},
        "build": {
            "output": f"build/{name}.pptx",
            "manifest": f"build/{name}.manifest.json",
        },
        "slides": [],
    }


def _scan_asset_warnings(
    design_data: Any, presentation_data: Any
) -> list[str]:
    warnings: list[str] = []

    def _is_local_reference(value: Any) -> bool:
        return isinstance(value, str) and bool(value) and "://" not in value

    if isinstance(design_data, dict):
        background_image = design_data.get("slide", {}).get("background_image")
        if _is_local_reference(background_image):
            warnings.append(
                f"design.yaml's slide.background_image ({background_image!r}) "
                "was not copied -- bring this asset over manually"
            )

    if isinstance(presentation_data, dict):
        standard_footnotes = (
            presentation_data.get("build", {}).get("reportifyr", {}).get("standard_footnotes")
        )
        if _is_local_reference(standard_footnotes):
            warnings.append(
                f"presentation.yaml's build.reportifyr.standard_footnotes "
                f"({standard_footnotes!r}) was not copied -- bring this file over manually"
            )

    return warnings


def materialize_template(
    resolved: ResolvedTemplate, target: Path, *, force: bool
) -> tuple[list[str], list[str]]:
    """Copy `resolved`'s files into `target`, generating a fresh
    `presentation.yaml` for a flat source (an empty-slide starter) or
    copying a typed source's own `presentation.yaml` verbatim (a real
    minimal starter for that presentation kind). Returns
    `(created_paths, warnings)`.

    Refuses (unless `force`) only on the exact destination paths this
    call is about to write already existing -- not on `target`'s whole
    non-emptiness, since pulling a template into an already-populated
    project directory (one that already has a `.git/`, `README.md`, ...)
    is this feature's own normal use case.
    """
    design_data = projectio.read_yaml(resolved.design_path)
    layouts_data = projectio.read_yaml(resolved.layouts_path)

    target.mkdir(parents=True, exist_ok=True)
    design_dest = target / resolved.design_filename
    layouts_dest = target / resolved.layouts_filename
    presentation_dest = target / "presentation.yaml"

    if resolved.kind == "typed":
        presentation_data = projectio.read_yaml(resolved.presentation_path)
        conflicts = [
            p for p in (design_dest, layouts_dest, presentation_dest) if p.exists()
        ]
    else:
        presentation_data = None
        conflicts = [p for p in (design_dest, layouts_dest) if p.exists()]

    if conflicts and not force:
        names = ", ".join(str(p) for p in conflicts)
        raise DeckifyrError(
            f"{names} already exist (use --force to overwrite)", code=ErrorCode.IO
        )

    created: list[str] = []
    shutil.copyfile(resolved.design_path, design_dest)
    created.append(str(design_dest))
    shutil.copyfile(resolved.layouts_path, layouts_dest)
    created.append(str(layouts_dest))

    if resolved.kind == "typed":
        shutil.copyfile(resolved.presentation_path, presentation_dest)
        created.append(str(presentation_dest))
    else:
        new_presentation = _build_minimal_presentation(target, resolved)
        try:
            PresentationDocument.model_validate(new_presentation)
        except PydanticValidationError as exc:  # pragma: no cover - defensive
            raise DeckifyrError(
                f"generated presentation.yaml failed validation: {exc}",
                code=ErrorCode.SCHEMA_VALIDATION,
            ) from exc
        projectio.write_yaml(presentation_dest, new_presentation)
        created.append(str(presentation_dest))

    warnings = _scan_asset_warnings(design_data, presentation_data)
    return created, warnings


# --- Orchestration entrypoint ---------------------------------------------


def init_from_template(
    target: Path,
    *,
    from_dir: str | None,
    from_repo: str | None,
    ref: str | None,
    subdir: str | None,
    type_name: str | None,
    force: bool,
) -> dict[str, Any]:
    """Single entrypoint `deckifyr.cli._cmd_init` calls for a template-
    based init (`--from-dir`/`--from-repo`). Resolves the source
    (a local directory as-is, or a git repo cloned to a temp dir), then
    detects and materializes the template. Returns
    `{"directory", "created", "warnings"}`.
    """
    if from_dir:
        source_dir = Path(from_dir)
        if not source_dir.is_dir():
            raise DeckifyrError(f"--from-dir not found: {source_dir}", code=ErrorCode.IO)
        resolved = detect_template(source_dir, type_name=type_name)
        created, warnings = materialize_template(resolved, target, force=force)
    else:
        assert from_repo is not None
        git_source = resolve_repo_spec(from_repo, ref=ref, subdir=subdir)
        with fetch_git_template(
            git_source.clone_url, ref=git_source.ref, subdir=git_source.subdir
        ) as source_dir:
            resolved = detect_template(source_dir, type_name=type_name)
            created, warnings = materialize_template(resolved, target, force=force)

    return {"directory": str(target), "created": created, "warnings": warnings}
