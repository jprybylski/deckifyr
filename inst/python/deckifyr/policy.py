"""What a project file is trusted to choose (issue #89).

A supervising launcher (a local workspace server) treats deck project files as
user data: they may supply options, but must never decide which executable
deckifyr runs or where it reads and writes outside the project. Left alone,
`presentation.yaml` can do both -- `build.quarto.binary`,
`build.preview.binary` and `build.reportifyr.flextable.binary` each accept "a
bare name looked up on PATH, or a full path", and `design.base`, `layouts`,
`build.output` and `build.manifest` are joined onto the project directory with
nothing stopping `..` or an absolute path.

`TrustPolicy` is the launcher's answer, in three independent pieces:

* **Binary overrides** (`--rscript-bin/--quarto-bin/--soffice-bin`, or
  `DECKIFYR_RSCRIPT_BIN`/`..._QUARTO_BIN`/`..._SOFFICE_BIN`): the launcher's
  own trusted executables, used instead of whatever the project file says.
* **`--trusted-binaries-only`** (`DECKIFYR_TRUSTED_BINARIES_ONLY`): a project
  file whose `binary` differs from the default bare name, with no override
  supplied for it, is rejected (`E_UNTRUSTED_BINARY`) -- nothing runs.
* **Path containment**, which rides on the same switch: under
  `--trusted-binaries-only`, `design.base`, `layouts`, `build.output`,
  `build.manifest`, `build.reportifyr.outputs_dir` and
  `build.reportifyr.standard_footnotes` must resolve (symlinks followed) inside
  the project root, else `E_PATH_OUTSIDE_PROJECT`; `--allow-outside-project`
  (`DECKIFYR_ALLOW_OUTSIDE_PROJECT`) relaxes that for a launcher that really
  does keep, say, a shared organization design outside each project.

Everything is off by default, so existing projects -- including ones that
legitimately point at a shared design outside their own tree -- behave exactly
as before. The element-level checks (an image, table, Quarto fragment or
reportifyr artifact escaping the project root) were never optional and are not
governed by any of this.

This module is mechanism only: it has no argparse and no I/O beyond resolving
paths. `deckifyr.cli` builds the policy from flags/environment; `projectio`,
`pptx.compose` and `deckifyr.web` consume it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from deckifyr.schema.errors import DeckifyrError, ErrorCode
from deckifyr.schema.presentation import (
    FlextableConfig,
    PresentationDocument,
    PreviewConfig,
    QuartoConfig,
)

# kind -> (flag, environment variable). One table so the CLI, the job
# splice-through and the docs cannot drift apart.
BINARY_KINDS: dict[str, tuple[str, str]] = {
    "rscript": ("--rscript-bin", "DECKIFYR_RSCRIPT_BIN"),
    "quarto": ("--quarto-bin", "DECKIFYR_QUARTO_BIN"),
    "soffice": ("--soffice-bin", "DECKIFYR_SOFFICE_BIN"),
}
TRUSTED_BINARIES_ONLY_FLAG = "--trusted-binaries-only"
TRUSTED_BINARIES_ONLY_ENV = "DECKIFYR_TRUSTED_BINARIES_ONLY"
ALLOW_OUTSIDE_PROJECT_FLAG = "--allow-outside-project"
ALLOW_OUTSIDE_PROJECT_ENV = "DECKIFYR_ALLOW_OUTSIDE_PROJECT"


def default_binary(kind: str) -> str:
    """The bare name a project file may keep using under the trust policy.

    Read from the pydantic models' own defaults, not restated here, so a
    changed default can never leave the policy comparing against a stale name.
    """
    model = {"rscript": FlextableConfig, "quarto": QuartoConfig, "soffice": PreviewConfig}[kind]
    return model.model_fields["binary"].default


# kind -> (project-file field path, accessor on a PresentationDocument)
def _project_binaries(presentation: PresentationDocument) -> dict[str, tuple[str, str | None]]:
    build = presentation.build
    flextable = build.reportifyr.flextable if build.reportifyr is not None else None
    return {
        "rscript": (
            "build.reportifyr.flextable.binary",
            flextable.binary if flextable is not None else None,
        ),
        "quarto": ("build.quarto.binary", build.quarto.binary if build.quarto else None),
        "soffice": ("build.preview.binary", build.preview.binary if build.preview else None),
    }


@dataclass(frozen=True)
class TrustPolicy:
    rscript_bin: str | None = None
    quarto_bin: str | None = None
    soffice_bin: str | None = None
    trusted_binaries_only: bool = False
    allow_outside_project: bool = False

    def override(self, kind: str) -> str | None:
        return {
            "rscript": self.rscript_bin,
            "quarto": self.quarto_bin,
            "soffice": self.soffice_bin,
        }[kind]

    def binary(self, kind: str, project_value: str | None) -> str:
        """The executable to run: the launcher's override, else the project
        file's value, else the default bare name."""
        return self.override(kind) or project_value or default_binary(kind)

    @property
    def contain_paths(self) -> bool:
        return self.trusted_binaries_only and not self.allow_outside_project

    def to_argv(self) -> list[str]:
        """The flags that recreate this policy -- spliced into a child
        `python -m deckifyr` (a web job) so it enforces the same policy."""
        argv: list[str] = []
        for kind, (flag, _env) in BINARY_KINDS.items():
            value = self.override(kind)
            if value:
                argv += [flag, value]
        if self.trusted_binaries_only:
            argv.append(TRUSTED_BINARIES_ONLY_FLAG)
        if self.allow_outside_project:
            argv.append(ALLOW_OUTSIDE_PROJECT_FLAG)
        return argv


PERMISSIVE = TrustPolicy()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_policy(args: object, env: Mapping[str, str]) -> TrustPolicy:
    """Flag > environment > off, for every field.

    `args` is an argparse namespace; attributes a subcommand never defined
    (the edit commands take no trust flags) simply fall through to the
    environment, which is how a launcher reaches them.
    """
    def pick(attr: str, env_name: str) -> str | None:
        value = getattr(args, attr, None)
        if value:
            return value
        return env.get(env_name) or None

    return TrustPolicy(
        rscript_bin=pick("rscript_bin", BINARY_KINDS["rscript"][1]),
        quarto_bin=pick("quarto_bin", BINARY_KINDS["quarto"][1]),
        soffice_bin=pick("soffice_bin", BINARY_KINDS["soffice"][1]),
        trusted_binaries_only=bool(getattr(args, "trusted_binaries_only", False))
        or _truthy(env.get(TRUSTED_BINARIES_ONLY_ENV)),
        allow_outside_project=bool(getattr(args, "allow_outside_project", False))
        or _truthy(env.get(ALLOW_OUTSIDE_PROJECT_ENV)),
    )


def check_binary_trust(presentation: PresentationDocument, policy: TrustPolicy) -> None:
    """Raise `E_UNTRUSTED_BINARY` if a project-file `binary` is not allowed.

    Only under `trusted_binaries_only`. A binary the launcher supplied an
    override for is not a problem even if the project file names another --
    the override wins and the project's value is never used.
    """
    if not policy.trusted_binaries_only:
        return
    for kind, (field_path, project_value) in _project_binaries(presentation).items():
        if project_value is None or project_value == default_binary(kind):
            continue
        if policy.override(kind):
            continue
        flag = BINARY_KINDS[kind][0]
        raise DeckifyrError(
            f"{field_path} is {project_value!r}, but this launcher only runs its own "
            f"trusted executables: remove the field (the default is "
            f"{default_binary(kind)!r}) or supply the executable with {flag}",
            code=ErrorCode.UNTRUSTED_BINARY,
        )


def resolve_in_project(project_root: Path, relative: str, field: str, policy: TrustPolicy) -> Path:
    """`project_root / relative`, resolved (symlinks followed); raise
    `E_PATH_OUTSIDE_PROJECT` when containment is enforced and it escapes.

    An absolute `relative` replaces the root in a path join, so `/etc/x` is
    caught the same way as `../../x`.
    """
    root = project_root.resolve()
    resolved = (root / relative).resolve()
    if policy.contain_paths:
        try:
            resolved.relative_to(root)
        except ValueError:
            raise DeckifyrError(
                f"{field} {relative!r} resolves to {resolved}, outside the project "
                f"directory {root}; keep it inside the project, or pass "
                f"{ALLOW_OUTSIDE_PROJECT_FLAG} if reading/writing there is intended",
                code=ErrorCode.PATH_OUTSIDE_PROJECT,
            ) from None
    return resolved


def check_project_paths(
    presentation: PresentationDocument, project_root: Path, policy: TrustPolicy
) -> None:
    """Containment for every project-file path the engine reads or writes
    outside the per-element resolvers. A no-op unless the policy enforces it."""
    if not policy.contain_paths:
        return
    build = presentation.build
    fields: list[tuple[str, str]] = [
        ("design.base", presentation.design.base),
        ("layouts", presentation.layouts),
        ("build.output", build.output),
    ]
    if build.manifest:
        fields.append(("build.manifest", build.manifest))
    if build.reportifyr is not None:
        fields.append(("build.reportifyr.outputs_dir", build.reportifyr.outputs_dir))
        if build.reportifyr.standard_footnotes:
            fields.append(
                ("build.reportifyr.standard_footnotes", build.reportifyr.standard_footnotes)
            )
    for field_name, value in fields:
        resolve_in_project(project_root, value, field_name, policy)


def check_presentation_policy(
    presentation: PresentationDocument, project_root: Path, policy: TrustPolicy
) -> None:
    """Both checks, in the order a launcher cares about: what would run, then
    where it would read and write."""
    check_binary_trust(presentation, policy)
    check_project_paths(presentation, project_root, policy)
