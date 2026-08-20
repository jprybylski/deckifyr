"""Shared schema-version validation (spec section 7.1: "Each schema must
contain an explicit Deckifyr schema version").

One constant and one validator, shared by design.py/layouts.py/
presentation.py, so the supported-version set only needs updating in one
place as the schema evolves.
"""

from __future__ import annotations

SUPPORTED_SCHEMA_VERSIONS = frozenset({"0.1"})

# The newest version in SUPPORTED_SCHEMA_VERSIONS -- update both together.
# Used wherever a brand-new document is generated (e.g. deckifyr.templates'
# template-init) rather than validated against an existing one.
CURRENT_SCHEMA_VERSION = "0.1"


def check_schema_version(value: str) -> str:
    if value not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ValueError(
            f"unsupported deckifyr schema version {value!r}; supported: {supported}"
        )
    return value
