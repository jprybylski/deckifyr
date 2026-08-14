"""CSV/Parquet table resolver (spec section 9.2's "CSV/Parquet table resolver").

Resolves a `table` element's `source` to normalized tabular data --
first row is treated as the header, same convention as `pandas`' own
`header=0` default. Path safety mirrors `deckifyr.resolvers.local`
exactly (project-relative only, no traversal) since a table source is
just as much a local file reference as an image's.

Parquet support is optional: `pyarrow` is not one of this package's core
dependencies (spec section 5's shared R-package/Python-wheel layout
keeps that dependency graph deliberately light), so it's imported lazily
and only a `.parquet` source pays for it. A project using only CSV
tables never needs it installed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from deckifyr.resolvers import BuildContext, ResolvedContent
from deckifyr.schema.errors import ContentValidationError

_SUPPORTED_SUFFIXES = {".csv", ".parquet"}


@dataclass
class TableData:
    headers: list[str]
    rows: list[list[str]]


def _resolve_local_path(value: str, context: BuildContext) -> Path:
    """Project-relative path resolution, duplicated (not imported) from
    `LocalFileResolver.resolve` -- that class returns a raw `Path` inside
    `ResolvedContent`, while this resolver needs the path only as an
    intermediate step before parsing, not as its own resolved value.
    """
    project_root = Path(context.project_root).resolve()
    candidate = (project_root / value).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise ContentValidationError(
            f"source {value!r} resolves outside the project root {project_root}"
        ) from exc
    if not candidate.is_file():
        raise ContentValidationError(f"source file not found: {candidate}")
    return candidate


def _read_csv(path: Path) -> TableData:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ContentValidationError(f"table source {path} is empty")
    headers, data_rows = rows[0], rows[1:]
    for row_index, row in enumerate(data_rows, start=2):
        if len(row) > len(headers):
            raise ContentValidationError(
                f"table source {path}, row {row_index}: has {len(row)} columns "
                f"but the header row has {len(headers)}"
            )
    return TableData(headers=headers, rows=data_rows)


def _read_parquet(path: Path) -> TableData:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ContentValidationError(
            f"table source {path} is a Parquet file, which requires the "
            "optional 'pyarrow' package (not installed) -- install it to "
            "resolve Parquet table sources"
        ) from exc

    table = pq.read_table(path)
    headers = table.column_names
    rows = [[str(value) for value in row] for row in zip(*(column.to_pylist() for column in table.columns))]
    return TableData(headers=headers, rows=rows)


class TableResolver:
    def supports(self, value: str) -> bool:
        if value.startswith("{rpfy}:"):
            return False
        return Path(value).suffix.lower() in _SUPPORTED_SUFFIXES

    def resolve(self, value: str, context: BuildContext) -> ResolvedContent:
        path = _resolve_local_path(value, context)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            data = _read_csv(path)
        elif suffix == ".parquet":
            data = _read_parquet(path)
        else:
            raise ContentValidationError(
                f"table source {value!r}: unsupported table format {suffix!r} "
                "(expected .csv or .parquet)"
            )
        return ResolvedContent(value=data)
