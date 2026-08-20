#!/usr/bin/env python3
"""Regenerate the static JSON Schema files under
inst/python/deckifyr/schemas/ from the live pydantic models
(deckifyr.schema.{design,layouts,presentation}) -- the same models
`deckifyr schema [design|layouts|presentation]`/R's `deck_schema()`
already dump on demand (spec section 11.1/11.2). Those two are for a
human or script invoking a command; the files this script writes are
for IDE YAML tooling (e.g. VS Code's YAML extension, via a
`# yaml-language-server: $schema=...` comment or a `yaml.schemas`
setting), which needs a real file path, not a command to run (issue
#49).

The checked-in files are enforced evergreen by
tests/python/test_json_schema_files.py, which regenerates each schema
in memory and compares it against what's on disk -- not by hand
verification. Run this script and commit the result whenever that test
fails (the same "regenerate, don't hand-edit" pattern
`Rscript -e 'roxygen2::roxygenise()'` already establishes for
NAMESPACE/man/*.Rd, see CONTRIBUTING.md).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inst" / "python"))

from deckifyr.schema.design import DesignDocument
from deckifyr.schema.layouts import LayoutsDocument
from deckifyr.schema.presentation import PresentationDocument

SCHEMA_MODELS = {
    "design": DesignDocument,
    "layouts": LayoutsDocument,
    "presentation": PresentationDocument,
}

OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "inst"
    / "python"
    / "deckifyr"
    / "schemas"
)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        path = OUTPUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
