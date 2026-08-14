"""Deep-merge precedence for design tokens (spec section 7.2).

Effective element = engine defaults < base design < org override <
project override < logical layout < slide-level override < element
inline style. Every step in that chain is the same operation applied
pairwise (`reduce(deep_merge, layers)`); this module only owns the
pairwise operation, not the specific layer list -- callers assemble the
chain themselves so this stays reusable for design, layout, and element
merges alike.
"""

from __future__ import annotations

from functools import reduce
from typing import Any, Mapping


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge `override` onto `base`.

    Dictionaries are merged recursively, key by key. Scalars and lists
    replace their parent value outright -- spec section 7.2 is explicit
    that lists are *not* concatenated unless a field defines additive
    behavior of its own, which is a schema-level concern, not this
    generic merge's job.
    """
    result = dict(base)
    for key, override_value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            result[key] = deep_merge(base_value, override_value)
        else:
            result[key] = override_value
    return result


def merge_chain(layers: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold a precedence-ordered list of layers (lowest first) into one dict."""
    return reduce(deep_merge, layers, {})
