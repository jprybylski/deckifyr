import pytest

from deckifyr import editor


# --- parse_path / get_value / set_value ---------------------------------


def test_parse_path_splits_dots_and_indices():
    assert editor.parse_path("a.b[2].c") == ["a", "b", 2, "c"]
    assert editor.parse_path("colors.primary") == ["colors", "primary"]
    assert editor.parse_path("slides[0]") == ["slides", 0]


def test_parse_path_rejects_empty_path():
    with pytest.raises(editor.PathError):
        editor.parse_path("")
    with pytest.raises(editor.PathError):
        editor.parse_path("   ")


def test_get_value_walks_nested_dicts_and_lists():
    document = {"colors": {"primary": "#2457A6"}, "slides": [{"id": "a", "notes": "hi"}]}
    assert editor.get_value(document, "colors.primary") == "#2457A6"
    assert editor.get_value(document, "slides[0].id") == "a"
    assert editor.get_value(document, "slides[0].notes") == "hi"


def test_get_value_supports_negative_index():
    document = {"slides": [{"id": "a"}, {"id": "b"}]}
    assert editor.get_value(document, "slides[-1].id") == "b"


def test_get_value_raises_path_error_for_missing_key():
    with pytest.raises(editor.PathError):
        editor.get_value({"colors": {}}, "colors.nope")


def test_get_value_raises_path_error_for_out_of_range_index():
    with pytest.raises(editor.PathError):
        editor.get_value({"slides": [{"id": "a"}]}, "slides[5].id")


def test_get_value_raises_path_error_when_indexing_a_non_list():
    with pytest.raises(editor.PathError):
        editor.get_value({"colors": {}}, "colors[0]")


def test_get_value_raises_path_error_when_keying_a_non_mapping():
    with pytest.raises(editor.PathError):
        editor.get_value({"colors": "not-a-dict"}, "colors.primary")


def test_set_value_replaces_an_existing_scalar():
    document = {"colors": {"primary": "#2457A6"}}
    editor.set_value(document, "colors.primary", "#123456")
    assert document["colors"]["primary"] == "#123456"


def test_set_value_adds_a_new_key_to_an_existing_mapping():
    # No auto-vivification of missing containers (editor.py's own
    # docstring), but a *new key* under an already-present mapping is
    # exactly the open-dict use case (design.yaml's colors/text_styles).
    document = {"colors": {"primary": "#2457A6"}}
    editor.set_value(document, "colors.brand", "#00FF00")
    assert document["colors"] == {"primary": "#2457A6", "brand": "#00FF00"}


def test_set_value_replaces_an_existing_list_element():
    document = {"slides": [{"id": "a"}, {"id": "b"}]}
    editor.set_value(document, "slides[1].id", "renamed")
    assert document["slides"][1]["id"] == "renamed"


def test_set_value_rejects_missing_parent_container():
    document = {}
    with pytest.raises(editor.PathError):
        editor.set_value(document, "colors.primary", "#123456")


def test_set_value_rejects_out_of_range_list_index():
    document = {"slides": [{"id": "a"}]}
    with pytest.raises(editor.PathError):
        editor.set_value(document, "slides[3].id", "x")


def test_set_value_returns_the_same_document_object():
    document = {"colors": {"primary": "old"}}
    result = editor.set_value(document, "colors.primary", "new")
    assert result is document


# --- detect_document_type ------------------------------------------------


def test_detect_document_type_presentation():
    assert editor.detect_document_type({"slides": [], "metadata": {}}) == "presentation"


def test_detect_document_type_design():
    assert editor.detect_document_type({"slide": {}, "fonts": {}}) == "design"


def test_detect_document_type_layouts():
    assert editor.detect_document_type({"layouts": {}}) == "layouts"


def test_detect_document_type_raises_on_unrecognized_shape():
    with pytest.raises(ValueError):
        editor.detect_document_type({"nothing": "recognizable"})


def test_detect_document_type_raises_on_non_mapping_root():
    with pytest.raises(ValueError):
        editor.detect_document_type(["not", "a", "mapping"])


# --- slide CRUD -----------------------------------------------------------


def _presentation(*slide_ids):
    return {
        "slides": [{"id": sid, "layout": "blank", "elements": {}} for sid in slide_ids]
    }


def test_list_slides_summarizes_each_slide():
    presentation = {
        "slides": [
            {"id": "a", "layout": "blank", "elements": {"x": {}}, "notes": "hi"},
            {"id": "b", "layout": None, "elements": []},
        ]
    }
    summaries = editor.list_slides(presentation)
    assert summaries == [
        {"id": "a", "layout": "blank", "element_count": 1, "has_notes": True},
        {"id": "b", "layout": None, "element_count": 0, "has_notes": False},
    ]


def test_add_slide_appends_by_default():
    presentation = _presentation("a", "b")
    editor.add_slide(presentation, id="c")
    assert [s["id"] for s in presentation["slides"]] == ["a", "b", "c"]
    assert presentation["slides"][-1]["layout"] is None


def test_add_slide_supports_after_before_and_index():
    presentation = _presentation("a", "b", "c")

    after = _presentation("a", "b", "c")
    editor.add_slide(after, id="new", after="a")
    assert [s["id"] for s in after["slides"]] == ["a", "new", "b", "c"]

    before = _presentation("a", "b", "c")
    editor.add_slide(before, id="new", before="c")
    assert [s["id"] for s in before["slides"]] == ["a", "b", "new", "c"]

    indexed = _presentation("a", "b", "c")
    editor.add_slide(indexed, id="new", index=0)
    assert [s["id"] for s in indexed["slides"]] == ["new", "a", "b", "c"]


def test_add_slide_only_writes_elements_and_notes_when_given():
    presentation = _presentation()
    editor.add_slide(presentation, id="a")
    assert presentation["slides"][0] == {"id": "a", "layout": None}


def test_add_slide_rejects_duplicate_id():
    presentation = _presentation("a")
    with pytest.raises(editor.DuplicateSlideIdError):
        editor.add_slide(presentation, id="a")


def test_add_slide_rejects_multiple_placement_args():
    presentation = _presentation("a", "b")
    with pytest.raises(editor.AmbiguousPlacementError):
        editor.add_slide(presentation, id="c", after="a", before="b")


def test_remove_slide_deletes_by_id():
    presentation = _presentation("a", "b", "c")
    editor.remove_slide(presentation, "b")
    assert [s["id"] for s in presentation["slides"]] == ["a", "c"]


def test_remove_slide_raises_for_unknown_id():
    presentation = _presentation("a")
    with pytest.raises(editor.SlideNotFoundError):
        editor.remove_slide(presentation, "nope")


def test_update_slide_only_touches_given_fields():
    presentation = _presentation("a")
    presentation["slides"][0]["notes"] = "original notes"
    editor.update_slide(presentation, "a", layout="new-layout")
    slide = presentation["slides"][0]
    assert slide["layout"] == "new-layout"
    assert slide["notes"] == "original notes"


def test_update_slide_can_clear_layout_and_notes():
    presentation = _presentation("a")
    presentation["slides"][0]["notes"] = "original notes"
    editor.update_slide(presentation, "a", layout=None, notes=None)
    slide = presentation["slides"][0]
    assert slide["layout"] is None
    assert "notes" not in slide


def test_update_slide_can_replace_elements():
    presentation = _presentation("a")
    editor.update_slide(presentation, "a", elements={"title": {"value": "hi"}})
    assert presentation["slides"][0]["elements"] == {"title": {"value": "hi"}}


def test_update_slide_raises_for_unknown_id():
    presentation = _presentation("a")
    with pytest.raises(editor.SlideNotFoundError):
        editor.update_slide(presentation, "nope", notes="hi")


def test_move_slide_reorders_by_index():
    presentation = _presentation("a", "b", "c")
    editor.move_slide(presentation, "c", index=0)
    assert [s["id"] for s in presentation["slides"]] == ["c", "a", "b"]


def test_move_slide_reorders_relative_to_another_slide():
    presentation = _presentation("a", "b", "c")
    editor.move_slide(presentation, "a", after="c")
    assert [s["id"] for s in presentation["slides"]] == ["b", "c", "a"]


def test_move_slide_relative_to_itself_raises_not_found():
    presentation = _presentation("a", "b")
    with pytest.raises(editor.SlideNotFoundError):
        editor.move_slide(presentation, "a", after="a")


def test_move_slide_rejects_multiple_placement_args():
    presentation = _presentation("a", "b")
    with pytest.raises(editor.AmbiguousPlacementError):
        editor.move_slide(presentation, "a", index=0, before="b")
