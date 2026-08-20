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


# --- layout CRUD (issue #30) -----------------------------------------------


def _layouts(*names):
    return {"layouts": {name: {"elements": {}} for name in names}}


def test_add_layout_appends_by_default():
    layouts = _layouts("blank")
    editor.add_layout(layouts, id="title-content")
    assert list(layouts["layouts"]) == ["blank", "title-content"]
    assert layouts["layouts"]["title-content"] == {"elements": {}}


def test_add_layout_accepts_starting_elements():
    layouts = _layouts("blank")
    editor.add_layout(layouts, id="title-content", elements={"title": {"type": "text"}})
    assert layouts["layouts"]["title-content"]["elements"] == {"title": {"type": "text"}}


def test_add_layout_rejects_duplicate_id():
    layouts = _layouts("blank")
    with pytest.raises(editor.DuplicateLayoutIdError):
        editor.add_layout(layouts, id="blank")


def test_remove_layout_deletes_by_id():
    layouts = _layouts("blank", "title-content")
    editor.remove_layout(layouts, "title-content")
    assert list(layouts["layouts"]) == ["blank"]


def test_remove_layout_raises_for_unknown_id():
    layouts = _layouts("blank")
    with pytest.raises(editor.LayoutNotFoundError):
        editor.remove_layout(layouts, "does-not-exist")


def test_remove_layout_refuses_to_remove_blank():
    layouts = _layouts("blank", "title-content")
    with pytest.raises(editor.UnremovableLayoutError):
        editor.remove_layout(layouts, "blank")


def test_layouts_using_finds_matching_slide_ids():
    presentation = {
        "slides": [
            {"id": "a", "layout": "title-content"},
            {"id": "b", "layout": "blank"},
            {"id": "c", "layout": "title-content"},
        ]
    }
    assert editor.layouts_using(presentation, "title-content") == ["a", "c"]
    assert editor.layouts_using(presentation, "blank") == ["b"]
    assert editor.layouts_using(presentation, "unused") == []


def test_reassign_layout_rewrites_matching_slides_only():
    presentation = {
        "slides": [
            {"id": "a", "layout": "title-content"},
            {"id": "b", "layout": "blank"},
        ]
    }
    editor.reassign_layout(presentation, "title-content", "blank")
    assert [s["layout"] for s in presentation["slides"]] == ["blank", "blank"]


# --- element CRUD (issue #31) -----------------------------------------------


def test_add_element_dict_form_inserts_by_id():
    elements = {"title": {"type": "text", "value": "hi"}}
    editor.add_element(elements, id="body", type="markdown", value="hello")
    assert elements["body"] == {"type": "markdown", "value": "hello"}


def test_add_element_defaults_none_to_dict_form():
    result = editor.add_element(None, id="title", type="text", value="hi")
    assert result == {"title": {"type": "text", "value": "hi"}}


def test_add_element_list_form_appends_with_id():
    elements = [{"id": "title", "type": "text"}]
    result = editor.add_element(elements, id="body", type="markdown", value="hi")
    assert result[-1] == {"id": "body", "type": "markdown", "value": "hi"}


def test_add_element_rejects_duplicate_id_dict_form():
    elements = {"title": {"type": "text"}}
    with pytest.raises(editor.DuplicateElementIdError):
        editor.add_element(elements, id="title", type="text")


def test_add_element_rejects_duplicate_id_list_form():
    elements = [{"id": "title", "type": "text"}]
    with pytest.raises(editor.DuplicateElementIdError):
        editor.add_element(elements, id="title", type="text")


def test_remove_element_dict_form_deletes_by_id():
    elements = {"title": {"type": "text"}, "body": {"type": "markdown"}}
    editor.remove_element(elements, "title")
    assert list(elements) == ["body"]


def test_remove_element_list_form_deletes_by_id():
    elements = [{"id": "title", "type": "text"}, {"id": "body", "type": "markdown"}]
    editor.remove_element(elements, "title")
    assert [e["id"] for e in elements] == ["body"]


def test_remove_element_raises_for_unknown_id_dict_form():
    with pytest.raises(editor.ElementNotFoundError):
        editor.remove_element({"title": {}}, "does-not-exist")


def test_remove_element_raises_for_unknown_id_list_form():
    with pytest.raises(editor.ElementNotFoundError):
        editor.remove_element([{"id": "title"}], "does-not-exist")
