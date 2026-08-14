from deckifyr.schema.merge import deep_merge, merge_chain


def test_deep_merge_recurses_into_nested_dicts():
    base = {"colors": {"text": "#000", "muted": "#555"}, "fonts": {"body": "Arial"}}
    override = {"colors": {"muted": "#666", "accent": "#F00"}}
    merged = deep_merge(base, override)
    assert merged == {
        "colors": {"text": "#000", "muted": "#666", "accent": "#F00"},
        "fonts": {"body": "Arial"},
    }


def test_deep_merge_replaces_scalars_and_lists_outright():
    base = {"tags": ["a", "b"], "rotation": 0}
    override = {"tags": ["c"], "rotation": 90}
    assert deep_merge(base, override) == {"tags": ["c"], "rotation": 90}


def test_deep_merge_does_not_mutate_inputs():
    base = {"x": {"y": 1}}
    override = {"x": {"z": 2}}
    deep_merge(base, override)
    assert base == {"x": {"y": 1}}
    assert override == {"x": {"z": 2}}


def test_merge_chain_folds_layers_in_precedence_order():
    layers = [
        {"overflow": "error", "rotation": 0},
        {"overflow": "shrink"},
        {"rotation": 90},
    ]
    assert merge_chain(layers) == {"overflow": "shrink", "rotation": 90}
