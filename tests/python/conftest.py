from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def minimal_deck_dir() -> Path:
    return REPO_ROOT / "inst" / "examples" / "minimal-deck"
