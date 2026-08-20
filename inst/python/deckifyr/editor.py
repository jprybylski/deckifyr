"""Programmatic editing of design/layouts/presentation YAML documents (spec
section 11.2's still-open "manipulate configs" gap, issue #10).

This module is deliberately the same kind of layer `deckifyr.plan` is
relative to `deckifyr.pptx.compose`: it operates on plain, already-parsed
YAML data (`dict`/`list`/scalar, exactly what `yaml.safe_load` returns),
never on a `pydantic` model and never touching a filesystem path itself.
`deckifyr.cli` and `deckifyr.web.app` are the only callers -- each owns
reading its own copy of a document (a file for `cli.py`, an in-memory
working copy for `app.py`), validating the edited result against the
right `deckifyr.schema` model before writing, and turning this module's
exceptions into a stable error code (`DeckifyrError` for the CLI,
`DeckifyrError` -> HTTP 422 for the web app), the same "orchestration
lives in the caller, mechanism lives in its own module" split
`_load_project`/`expand_presentation` already follow. Only the CLI
exposes every capability below as a subcommand, though -- layout CRUD
and element CRUD (issues #30/#31) are web-editor-only today, the same
precedent furniture CRUD (issue #21) and layout-zone editing (issue
#23) already set: real, tested, callable from `app.py`, with no `cli.py`
subcommand or R wrapper.

Four independent capabilities, all operating on the raw dict a document
parses to:

- **Path get/set** (`get_value`/`set_value`), a small dotted-path (plus
  `[N]` list indices) accessor usable against any of the three document
  shapes -- `colors.primary`, `slides[0].notes`, `text_styles.title.size`.
  `set_value` deliberately does not auto-vivify missing containers (spec
  section 20 warning 7's "no silent magic" spirit applies to editing as
  much as to compositing): the parent of the final path segment must
  already exist. This is what lets `colors.a_brand_new_token` be *set* on
  an already-present `colors:` mapping (an open dict, spec section 7.4)
  while still failing loudly, rather than silently materializing a
  `colors: {}` block, on a `design.yaml` that omitted `colors:` entirely.
- **Slide CRUD** (`list_slides`/`add_slide`/`remove_slide`/
  `update_slide`/`move_slide`), scoped to `presentation.yaml`'s own
  `slides` list -- the one place spec section 7.6 singles out as needing
  id-keyed, not index-keyed, operations ("Named elements are essential.
  Array indices should never be the primary override mechanism.").
  `after`/`before` (an existing slide id) and `index` (a raw position)
  are three ways to say the same thing -- placement -- so every function
  that takes them rejects more than one being set rather than picking a
  silent precedence order.
- **Layout CRUD** (`add_layout`/`remove_layout`/`layouts_using`/
  `reassign_layout`, issue #30), scoped to `layouts.yaml`'s own
  `layouts` mapping. Unlike slides, a layout has no meaningful order to
  place it in (it's a dict, not a list a user reads top-to-bottom), so
  there's no `after`/`before`/`index` here. `remove_layout` refuses to
  remove `deckifyr.schema.layouts.BLANK_LAYOUT_ID` -- every
  `layouts.yaml` is required to define it -- and doesn't touch
  `presentation.yaml` on its own; `layouts_using`/`reassign_layout` are
  the separate, `presentation.yaml`-side half of "reassign every slide
  that used the removed layout to `blank`", left as two small functions
  rather than one that reaches across both documents, since every other
  function here only ever touches the one document its own name says it
  does.
- **Element CRUD** (`add_element`/`remove_element`, issue #31),
  usable against *either* a slide's `elements` block
  (`presentation.yaml`) or a layout's `elements` block
  (`layouts.yaml`) -- both are the same dict-or-list shape (spec
  section 7.6), so one pair of functions covers both documents. This is
  the "third CRUD surface" a slide's `elements` previously only had
  wholesale replacement for (`add_slide`'s/`update_slide`'s own
  `elements` parameter) -- editing a single *existing* element's fields
  is still a `set_value` call against that element's own path (e.g.
  `slides[0].elements.title.value`), not something `add_element`/
  `remove_element` do.
"""

from __future__ import annotations

import re
from typing import Any

from deckifyr.schema.layouts import BLANK_LAYOUT_ID

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(-?\d+)\]")

# Sentinel distinguishing "leave this field alone" from "set it to None"
# in update_slide's keyword arguments -- `layout: null`/no `notes` are
# both meaningful, valid values (spec section 7.6), so `None` itself
# can't double as "not passed".
UNSET = object()


class PathError(ValueError):
    """A `get_value`/`set_value` path did not resolve against the document."""


class SlideNotFoundError(ValueError):
    """No slide in `presentation.yaml`'s `slides` list has the given id."""


class DuplicateSlideIdError(ValueError):
    """`add_slide` was asked to reuse an id already present in `slides`."""


class AmbiguousPlacementError(ValueError):
    """More than one of `index`/`after`/`before` was given for a placement."""


class LayoutNotFoundError(ValueError):
    """No layout in `layouts.yaml`'s `layouts` mapping has the given id."""


class DuplicateLayoutIdError(ValueError):
    """`add_layout` was asked to reuse an id already present in `layouts`."""


class UnremovableLayoutError(ValueError):
    """`remove_layout` was asked to remove the required `blank` layout
    (spec-adjacent, issue #30: every `layouts.yaml` must keep one)."""


class ElementNotFoundError(ValueError):
    """No element in an `elements` dict/list has the given id."""


class DuplicateElementIdError(ValueError):
    """`add_element` was asked to reuse an id already present in `elements`."""


# --- Dotted-path get/set -----------------------------------------------


def parse_path(path: str) -> list[str | int]:
    """Split `"a.b[2].c"` into `["a", "b", 2, "c"]`.

    `.` separates mapping keys; `[N]` (immediately following the previous
    token, no `.` needed) indexes a list. Negative indices are accepted,
    matching ordinary Python/list semantics.
    """
    if not path or not path.strip():
        raise PathError("path must not be empty")
    tokens: list[str | int] = []
    for match in _PATH_TOKEN_RE.finditer(path):
        key, index = match.groups()
        tokens.append(key if key is not None else int(index))
    if not tokens:
        raise PathError(f"could not parse path {path!r}")
    return tokens


def _describe(tokens: list[str | int]) -> str:
    rendered = ""
    for token in tokens:
        if isinstance(token, int):
            rendered += f"[{token}]"
        else:
            rendered += f".{token}" if rendered else str(token)
    return rendered or "<root>"


def _step(current: Any, token: str | int, tokens_so_far: list[str | int]) -> Any:
    if isinstance(token, int):
        if not isinstance(current, list):
            raise PathError(f"{_describe(tokens_so_far[:-1])} is not a list")
        if not -len(current) <= token < len(current):
            raise PathError(f"{_describe(tokens_so_far)}: index out of range")
        return current[token]
    if not isinstance(current, dict):
        raise PathError(f"{_describe(tokens_so_far[:-1])} is not a mapping")
    if token not in current:
        raise PathError(f"{_describe(tokens_so_far)}: key not found")
    return current[token]


def get_value(document: Any, path: str) -> Any:
    """Return the value at `path` within `document` (raises `PathError`)."""
    tokens = parse_path(path)
    current = document
    for i in range(len(tokens)):
        current = _step(current, tokens[i], tokens[: i + 1])
    return current


def set_value(document: Any, path: str, value: Any) -> Any:
    """Set `path` to `value` in place and return `document`.

    The parent of the final path segment must already exist -- see this
    module's own docstring on why there's no auto-vivification. Setting a
    list element requires that index to already exist; inserting into a
    list is `add_slide`/a future analogous element-insertion helper's
    job, not this function's.
    """
    tokens = parse_path(path)
    parent = document
    for i in range(len(tokens) - 1):
        parent = _step(parent, tokens[i], tokens[: i + 1])
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(parent, list):
            raise PathError(f"{_describe(tokens[:-1])} is not a list")
        if not -len(parent) <= last < len(parent):
            raise PathError(
                f"{_describe(tokens)}: index out of range -- set only replaces "
                "an existing list element"
            )
        parent[last] = value
    else:
        if not isinstance(parent, dict):
            raise PathError(f"{_describe(tokens[:-1])} is not a mapping")
        parent[last] = value
    return document


def detect_document_type(data: Any) -> str:
    """Guess whether `data` is a design/layouts/presentation document,
    from its own top-level keys -- each of the three schemas (spec
    sections 7.4/7.5/7.6) has a distinct, required shape, so this needs
    no `deckifyr:` field parsing or version lookup.
    """
    if not isinstance(data, dict):
        raise ValueError("document root must be a mapping")
    if "slides" in data and "metadata" in data:
        return "presentation"
    if "slide" in data and "fonts" in data:
        return "design"
    if "layouts" in data:
        return "layouts"
    raise ValueError(
        "could not determine document type from its top-level keys -- expected "
        "a design.yaml, layouts.yaml, or presentation.yaml shape"
    )


# --- presentation.yaml slide CRUD ---------------------------------------


def list_slides(presentation: dict) -> list[dict[str, Any]]:
    """Summarize `presentation["slides"]` in order: `id`, `layout`,
    `element_count`, `has_notes`.
    """
    slides = presentation.get("slides") or []
    summaries = []
    for slide in slides:
        elements = slide.get("elements") or {}
        summaries.append(
            {
                "id": slide.get("id"),
                "layout": slide.get("layout"),
                "element_count": len(elements),
                "has_notes": slide.get("notes") is not None,
            }
        )
    return summaries


def _find_slide_index(slides: list[dict], slide_id: str) -> int:
    for i, slide in enumerate(slides):
        if slide.get("id") == slide_id:
            return i
    raise SlideNotFoundError(f"no slide with id {slide_id!r}")


def _resolve_placement(
    slides: list[dict],
    *,
    index: int | None,
    after: str | None,
    before: str | None,
) -> int:
    given = [value is not None for value in (index, after, before)]
    if sum(given) > 1:
        raise AmbiguousPlacementError("specify at most one of index/after/before")
    if after is not None:
        return _find_slide_index(slides, after) + 1
    if before is not None:
        return _find_slide_index(slides, before)
    if index is not None:
        return max(0, min(index, len(slides)))
    return len(slides)


def add_slide(
    presentation: dict,
    *,
    id: str,
    layout: str | None = None,
    elements: dict | list | None = None,
    notes: str | None = None,
    index: int | None = None,
    after: str | None = None,
    before: str | None = None,
) -> dict:
    """Insert a new slide into `presentation["slides"]`.

    `layout: None` is `Slide`'s own valid "freeform" value (spec section
    7.6), not "unset" -- a new slide always gets an explicit `layout` key,
    matching how a hand-written `presentation.yaml` slide entry looks.
    `elements`/`notes` are only written at all when given (an omitted
    `elements` block matches the schema's own `elements: {}` default, so
    there's no reason to write it out).
    """
    slides = presentation.setdefault("slides", [])
    if any(slide.get("id") == id for slide in slides):
        raise DuplicateSlideIdError(f"slide id {id!r} already exists")
    new_slide: dict[str, Any] = {"id": id, "layout": layout}
    if elements is not None:
        new_slide["elements"] = elements
    if notes is not None:
        new_slide["notes"] = notes
    slides.insert(
        _resolve_placement(slides, index=index, after=after, before=before), new_slide
    )
    return presentation


def remove_slide(presentation: dict, slide_id: str) -> dict:
    """Remove the slide with id `slide_id` from `presentation["slides"]`."""
    slides = presentation.get("slides") or []
    del slides[_find_slide_index(slides, slide_id)]
    return presentation


def update_slide(
    presentation: dict,
    slide_id: str,
    *,
    layout: Any = UNSET,
    notes: Any = UNSET,
    elements: Any = UNSET,
) -> dict:
    """Update fields on the slide with id `slide_id` in place.

    Each of `layout`/`notes`/`elements` defaults to the `UNSET` sentinel
    (leave alone); pass `None` explicitly to clear a field (`layout:
    null`, or dropping `notes` entirely) -- see this module's own
    docstring for why `None` can't double as both meanings.
    """
    slides = presentation.get("slides") or []
    slide = slides[_find_slide_index(slides, slide_id)]
    if layout is not UNSET:
        slide["layout"] = layout
    if notes is not UNSET:
        if notes is None:
            slide.pop("notes", None)
        else:
            slide["notes"] = notes
    if elements is not UNSET:
        slide["elements"] = elements
    return presentation


def move_slide(
    presentation: dict,
    slide_id: str,
    *,
    index: int | None = None,
    after: str | None = None,
    before: str | None = None,
) -> dict:
    """Reorder the slide with id `slide_id` within `presentation["slides"]`.

    `after`/`before` are resolved against the list with `slide_id`
    already removed, so moving a slide relative to itself (a no-op
    placement) correctly raises `SlideNotFoundError` rather than
    silently succeeding.
    """
    slides = presentation.get("slides") or []
    slide = slides.pop(_find_slide_index(slides, slide_id))
    slides.insert(
        _resolve_placement(slides, index=index, after=after, before=before), slide
    )
    return presentation


# --- layouts.yaml layout CRUD (issue #30) -------------------------------


def add_layout(layouts: dict, *, id: str, elements: dict | None = None) -> dict:
    """Insert a new layout into `layouts["layouts"]`.

    Unlike `add_slide`, there's no placement/`after`/`before` concept --
    `layouts` is a dict, not an ordered list a user scans top-to-bottom
    the way `presentation.yaml`'s `slides` is, so a new layout is always
    appended at the end; dict insertion order is what a `sort_keys=False`
    YAML dump round-trips (`deckifyr.cli._write_yaml`'s own established
    precedent for every other document this module edits).
    """
    entries = layouts.setdefault("layouts", {})
    if id in entries:
        raise DuplicateLayoutIdError(f"layout id {id!r} already exists")
    entries[id] = {"elements": elements or {}}
    return layouts


def remove_layout(layouts: dict, name: str) -> dict:
    """Remove the layout `name` from `layouts["layouts"]`.

    `blank` (`deckifyr.schema.layouts.BLANK_LAYOUT_ID`) can never be
    removed -- every `layouts.yaml` is required to define it (issue
    #30's new schema validator), and it's the fallback `reassign_layout`
    below rewrites affected slides to when their own layout is removed.
    """
    if name == BLANK_LAYOUT_ID:
        raise UnremovableLayoutError(f"the {BLANK_LAYOUT_ID!r} layout can't be removed")
    entries = layouts.get("layouts") or {}
    if name not in entries:
        raise LayoutNotFoundError(f"no layout with id {name!r}")
    del entries[name]
    return layouts


def layouts_using(presentation: dict, layout_name: str) -> list[str]:
    """Ids of every slide in `presentation["slides"]` whose `layout`
    field is `layout_name` -- used by `deckifyr.web.app`'s layout-removal
    route to know which slides `reassign_layout` is about to touch."""
    return [
        slide["id"]
        for slide in presentation.get("slides") or []
        if slide.get("layout") == layout_name
    ]


def reassign_layout(presentation: dict, old_layout: str, new_layout: str) -> dict:
    """Rewrite every slide referencing `old_layout` to use `new_layout`
    instead -- the other half of removing a layout that's still in use
    (issue #30's "impacted slides will be considered blank layout
    type")."""
    for slide in presentation.get("slides") or []:
        if slide.get("layout") == old_layout:
            slide["layout"] = new_layout
    return presentation


# --- slide/layout element CRUD (issue #31) ------------------------------


def add_element(
    elements: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    id: str,
    type: str,
    **fields: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Insert a new element into a slide's or layout's `elements` block.

    `elements` may be the dict-keyed form (`{id: {...}}`, the common
    case, and what a `None` input defaults to) or the list-keyed
    freeform form (`[{id: ..., ...}]`, spec section 7.6) -- whichever
    shape the input already is, the output stays that shape, mirroring
    `deckifyr.web.app.patch_element`'s existing dict-vs-list handling
    rather than silently converting one slide's list-form elements into
    dict form.
    """
    body = {"type": type, **fields}
    if isinstance(elements, list):
        if any(isinstance(e, dict) and e.get("id") == id for e in elements):
            raise DuplicateElementIdError(f"element id {id!r} already exists")
        elements.append({"id": id, **body})
        return elements
    elements = {} if elements is None else elements
    if id in elements:
        raise DuplicateElementIdError(f"element id {id!r} already exists")
    elements[id] = body
    return elements


def remove_element(
    elements: dict[str, Any] | list[dict[str, Any]], id: str
) -> dict[str, Any] | list[dict[str, Any]]:
    """Remove the element with id `id` from a slide's or layout's
    `elements` block, in either its dict- or list-keyed form."""
    if isinstance(elements, list):
        index = next(
            (i for i, e in enumerate(elements) if isinstance(e, dict) and e.get("id") == id),
            None,
        )
        if index is None:
            raise ElementNotFoundError(f"no element with id {id!r}")
        del elements[index]
        return elements
    if not isinstance(elements, dict) or id not in elements:
        raise ElementNotFoundError(f"no element with id {id!r}")
    del elements[id]
    return elements
