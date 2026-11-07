"""Text encoding for project files (issue #94).

Project YAML/JSON/CSV/QMD files are read as UTF-8 *with* an optional byte
order mark. Windows tools write one -- Windows PowerShell 5.1's
`Set-Content -Encoding utf8`, older Notepad -- and an unstripped BOM becomes
part of the first YAML key (`\\ufeffdeckifyr`) or CSV header, which fails
schema validation with an error that looks like a missing field. `utf-8-sig`
removes a BOM when present and is otherwise identical to `utf-8`.

Reading with an explicit encoding also stops `Path.read_text()` falling back
to the locale encoding (cp1252 on Windows), which mis-decodes non-ASCII text
in a UTF-8 file. Files deckifyr *writes* stay BOM-less UTF-8
(`WRITE_ENCODING`).
"""

from __future__ import annotations

from pathlib import Path

READ_ENCODING = "utf-8-sig"
WRITE_ENCODING = "utf-8"


def read_project_text(path: Path) -> str:
    """Read a project text file as UTF-8, dropping a leading BOM."""
    return path.read_text(encoding=READ_ENCODING)
