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
from deckifyr.schema.results import RESULT_MODELS, result_json_schema

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


RESULTS_DIR = SCHEMAS_DIR / "results"


def test_every_result_type_has_a_checked_in_schema_file():
    on_disk = {p.stem.removesuffix(".schema") for p in RESULTS_DIR.glob("*.schema.json")}
    assert on_disk == set(RESULT_MODELS)


def test_checked_in_result_schema_files_match_the_live_models():
    stale = [
        name
        for name, model in RESULT_MODELS.items()
        if json.loads((RESULTS_DIR / f"{name}.schema.json").read_text())
        != result_json_schema(name, model)
    ]
    assert not stale, (
        f"result schemas {stale} out of date -- run "
        "`python scripts/generate_json_schemas.py` and commit the result"
    )


def _closed_objects(node, path=""):
    """Every object schema inside `node` that forbids extra properties."""
    found = []
    if isinstance(node, dict):
        if node.get("additionalProperties") is False:
            found.append(path or "<root>")
        for key, value in node.items():
            found.extend(_closed_objects(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_closed_objects(value, f"{path}/{i}"))
    return found


def test_result_schemas_allow_extra_keys_as_documented():
    # The docs promise adding a key to a result is not a breaking change; a
    # schema that closed its objects would reject such a payload (issue #91).
    for name in RESULT_MODELS:
        schema = json.loads((RESULTS_DIR / f"{name}.schema.json").read_text())
        assert _closed_objects(schema) == [], name


def test_result_schemas_carry_a_versioned_id():
    from deckifyr.schema.results import RESULT_VERSION

    for name in RESULT_MODELS:
        schema = json.loads((RESULTS_DIR / f"{name}.schema.json").read_text())
        assert schema["$id"].endswith(f"/v{RESULT_VERSION}/{name}.schema.json")
        assert schema["$schema"].startswith("https://json-schema.org/")
