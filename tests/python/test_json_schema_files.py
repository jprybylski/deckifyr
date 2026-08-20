"""Keeps inst/python/deckifyr/schemas/*.schema.json (the static JSON
Schema files IDE YAML tooling points at, issue #49) evergreen without
hand verification: each checked-in file must match what the live
pydantic model produces right now. A model change that isn't followed
by `python scripts/generate_json_schemas.py` fails this test instead of
silently drifting.
"""

import json
from pathlib import Path

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument

SCHEMA_MODELS = {
    "design": DesignDocument,
    "layouts": LayoutsDocument,
    "presentation": PresentationDocument,
}

SCHEMAS_DIR = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "python"
    / "deckifyr"
    / "schemas"
)


def test_every_document_type_has_a_checked_in_schema_file():
    on_disk = {p.stem.removesuffix(".schema") for p in SCHEMAS_DIR.glob("*.schema.json")}
    assert on_disk == set(SCHEMA_MODELS)


def test_checked_in_schema_files_match_the_live_models():
    stale = []
    for name, model in SCHEMA_MODELS.items():
        path = SCHEMAS_DIR / f"{name}.schema.json"
        on_disk = json.loads(path.read_text())
        if on_disk != model.model_json_schema():
            stale.append(name)
    assert not stale, (
        f"{stale} out of date -- run `python scripts/generate_json_schemas.py` "
        "and commit the result"
    )
