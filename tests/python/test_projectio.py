import pytest

from deckifyr import projectio
from deckifyr.schema.errors import DeckifyrError

_PRESENTATION = {
    "deckifyr": "0.1",
    "design": {"base": "design.yaml"},
    "layouts": "layouts.yaml",
    "metadata": {"title": "Test"},
    "build": {"output": "build/out.pptx"},
    "slides": [{"id": "only-slide", "layout": "custom", "elements": {}}],
}


def test_validate_presentation_data_uses_layouts_data_over_disk_when_given(tmp_path):
    # No layouts.yaml on disk at all -- if `layouts_data` weren't
    # actually used, this would either 500 on a missing file or (per the
    # disk-read branch's own best-effort semantics) silently skip the
    # cross-check instead of validating against what's passed in.
    presentation = projectio.validate_presentation_data(
        tmp_path / "presentation.yaml",
        _PRESENTATION,
        layouts_data={"deckifyr": "0.1", "layouts": {"custom": {}, "blank": {}}},
    )
    assert presentation.slides[0].layout == "custom"


def test_validate_presentation_data_rejects_unknown_layout_in_layouts_data(tmp_path):
    with pytest.raises(DeckifyrError, match="unknown layout 'custom'"):
        projectio.validate_presentation_data(
            tmp_path / "presentation.yaml",
            _PRESENTATION,
            layouts_data={"deckifyr": "0.1", "layouts": {"blank": {}}},
        )


def test_validate_presentation_data_falls_back_to_disk_when_layouts_data_omitted(tmp_path):
    (tmp_path / "layouts.yaml").write_text("deckifyr: '0.1'\nlayouts: {blank: {}}\n")
    with pytest.raises(DeckifyrError, match="unknown layout 'custom'"):
        projectio.validate_presentation_data(tmp_path / "presentation.yaml", _PRESENTATION)
