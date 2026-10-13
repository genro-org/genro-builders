# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Export a builder's `_class_schema` to a `builder_grammar` document.

The neutral JSON format produced here is the runtime contract between
the Python builder (producer) and consumers in other environments
(JavaScript builder, the Python loader of ``_grammar_documents`` in
``_grammar_load.py``, downstream transpilers).

The format is specified in `GRAMMAR_FORMAT.md`, co-located with this
module. This module is the **producer** side: it reads a builder
class's `_class_schema` Bag (populated by `__init_subclass__`) and
returns a dict that, when serialised with `json.dumps`, matches the
spec.

Exports:
    _class_schema_to_grammar_document: build the document dict.
"""

from __future__ import annotations

import copy
import inspect
import math
import types
from collections.abc import Callable
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from ._utilities import SIGNATURE_SKIP_PARAMS
from ._validators import Range, Regex

FORMAT_NAME = "builder_grammar"
FORMAT_VERSION = "1.1"
CUSTOM_TYPES_FORMAT_VERSION = "1.2"


def _topological_sort(
    keys: list[str],
    get_deps: Callable[[str], list[str]],
) -> list[str]:
    """Return ``keys`` ordered so that each key comes after its deps.

    Dependencies returned by ``get_deps`` that are not in ``keys`` are
    treated as external (already emitted in another section) and
    ignored for ordering purposes.

    Ties break on the original insertion order of ``keys``: keys that
    are independent (no internal deps) keep their relative order.

    The implementation is Kahn's algorithm with an FIFO queue that
    preserves insertion order among ready nodes.
    """
    keys_set = set(keys)
    indegree: dict[str, int] = dict.fromkeys(keys, 0)
    edges: dict[str, list[str]] = {k: [] for k in keys}
    for k in keys:
        for dep in get_deps(k):
            if dep in keys_set and dep != k:
                edges[dep].append(k)
                indegree[k] += 1

    ready = [k for k in keys if indegree[k] == 0]
    out: list[str] = []
    while ready:
        # FIFO -> keep insertion order among ready nodes
        k = ready.pop(0)
        out.append(k)
        for succ in edges[k]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                ready.append(succ)

    if len(out) != len(keys):
        # Cycle in inherits_from. Should not happen in practice but
        # report explicitly rather than emit a partial document.
        remaining = [k for k in keys if k not in out]
        raise ValueError(
            f"Cycle in inherits_from chain involving: {remaining}"
        )
    return out


def _parse_inherits_from(raw: Any) -> list[str]:
    """Return the list of parent names declared in ``raw``."""
    if not raw:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def _json_value(value: Any, path: str) -> Any:
    """Copy JSON data; refuse what JSON cannot carry losslessly."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [_json_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _json_value(v, f"{path}.{k}") for k, v in value.items()}
    raise TypeError(f"{path}: cannot export {type(value).__name__} losslessly as JSON")


def _annotation_form(annotation: Any, path: str, custom_types: dict | None = None) -> Any:
    """JSON descriptor of a parameter annotation (``None`` if absent)."""
    if annotation is inspect.Parameter.empty:
        return None
    if annotation is Any:
        return {"kind": "any"}
    if annotation is Ellipsis:
        return {"kind": "ellipsis"}
    from .custom_types import _CustomType

    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        registered = [item for item in args[1:] if isinstance(item, _CustomType)]
        if registered:
            if len(args) != 2 or len(registered) != 1 or custom_types is None:
                raise TypeError(f"{path}: custom types require a catalog and cannot be re-annotated")
            item = registered[0]
            definition = _annotation_form(Annotated[item.base, item.annotation], path)
            # Validate portability at export, not only when a consumer loads it.
            from ._grammar_load import _custom_types
            _custom_types({item.name: definition})
            if item.name in custom_types and custom_types[item.name] != definition:
                raise TypeError(f"{path}: conflicting custom type {item.name!r}")
            custom_types[item.name] = definition
            return {"kind": "custom", "name": item.name}
    if origin is Annotated:
        metadata = []
        for item in args[1:]:
            if type(item) is Regex:
                metadata.append({"kind": "regex", "pattern": item.pattern, "flags": int(item.flags)})
            elif type(item) is Range:
                metadata.append({"kind": "range", **{
                    k: _json_value(getattr(item, k), f"{path}.{k}")
                    for k in ("ge", "le", "gt", "lt")
                }})
            elif callable(item):
                raise TypeError(f"{path}: unsupported callable annotation metadata; "
                                "a portable validator descriptor is required")
            else:
                metadata.append({"kind": "value", "value": _json_value(item, path)})
        return {"kind": "annotated", "base": _annotation_form(args[0], path, custom_types), "metadata": metadata}
    if origin in (Union, types.UnionType):
        return {"kind": "union", "items": [_annotation_form(a, path, custom_types) for a in args]}
    if origin is Literal:
        return {"kind": "literal", "values": [_json_value(a, path) for a in args]}
    if isinstance(annotation, list):  # typing.Callable argument list
        return {"kind": "arguments", "items": [_annotation_form(a, path, custom_types) for a in annotation]}
    if origin is not None:
        return {"kind": "generic", "origin": _annotation_form(origin, path, custom_types),
                "arguments": [_annotation_form(a, path, custom_types) for a in args]}
    if isinstance(annotation, type) and "<locals>" not in annotation.__qualname__:
        return {"kind": "type", "module": annotation.__module__, "name": annotation.__qualname__}
    raise TypeError(f"{path}: unsupported annotation {annotation!r}")


def _attributes_form(node: Any, custom_types: dict) -> dict[str, Any] | None:
    """JSON ``attributes`` of a schema node.

    A decorated declaration carries its ``declaration_signature``; a
    declaration read from a document carries the document's
    ``attributes`` verbatim, so it is written back unchanged.
    """
    for name, definition in (node.get_attr("custom_types") or {}).items():
        if name in custom_types and custom_types[name] != definition:
            raise TypeError(f"conflicting custom type {name!r}")
        custom_types[name] = copy.deepcopy(definition)
    signature = node.get_attr("declaration_signature")
    if signature is None:
        attributes: dict[str, Any] | None = copy.deepcopy(node.get_attr("attributes"))
        return attributes
    parameters = []
    for name, parameter in signature.parameters.items():
        path = f"{node.label}.{name}"
        has_default = parameter.default is not inspect.Parameter.empty
        item = {
            "name": name,
            "kind": parameter.kind.name.lower(),
            "role": "framework" if name in SIGNATURE_SKIP_PARAMS else (
                "value" if name == "node_value" else "attribute"),
            "annotation": _annotation_form(parameter.annotation, path, custom_types),
            "has_default": has_default,
        }
        if has_default:
            item["default"] = _json_value(parameter.default, f"{path}.default")
        parameters.append(item)
    kinds = {p.kind for p in signature.parameters.values()}
    return {
        "parameters": parameters,
        "accepts_var_keyword": inspect.Parameter.VAR_KEYWORD in kinds,
        "accepts_var_positional": inspect.Parameter.VAR_POSITIONAL in kinds,
    }


def _meta_copy(node: Any) -> dict[str, Any] | None:
    """JSON copy of the node's ``_meta``; an empty ``{}`` stays ``{}``.

    Raises ``TypeError`` on a value JSON cannot carry losslessly.
    """
    meta = node.get_attr("_meta")
    return _json_value(meta, f"{node.label}._meta") if meta is not None else None


def _abstract_form(node: Any, custom_types: dict) -> dict[str, Any]:
    """JSON form of an abstract node."""
    inherits_from = node.get_attr("inherits_from") or None
    return {
        "doc": node.get_attr("documentation"),
        "sub_tags": node.get_attr("sub_tags"),
        "parent_tags": node.get_attr("parent_tags"),
        "inherits_from": inherits_from,
        "ns": node.get_attr("ns"),
        "attributes": _attributes_form(node, custom_types),
        "_meta": _meta_copy(node),
    }


def _element_form(node: Any, custom_types: dict) -> dict[str, Any]:
    """JSON form of an element node."""
    inherits_from = node.get_attr("inherits_from") or None
    return {
        "doc": node.get_attr("documentation"),
        "sub_tags": node.get_attr("sub_tags"),
        "parent_tags": node.get_attr("parent_tags"),
        "inherits_from": inherits_from,
        "ns": node.get_attr("ns"),
        "attributes": _attributes_form(node, custom_types),
        "node_label": node.get_attr("node_label"),
        "collection_key": node.get_attr("collection_key"),
        "_meta": _meta_copy(node),
    }


def _section_topologically_sorted(
    raw_items: dict[str, dict[str, Any]],
    insertion_order: list[str],
) -> dict[str, dict[str, Any]]:
    """Topologically sort a section's items by their `inherits_from`.

    `raw_items` keeps the per-key forms produced by `_*_form`.
    `insertion_order` is the original order of keys as seen in the
    schema. Returned dict has the same keys, reordered.

    Dependencies that point outside this section (typical case:
    elements inherit from abstracts) are ignored — only intra-section
    edges constrain the order.
    """
    def get_deps(k: str) -> list[str]:
        # Read `inherits_from` if the form declares one. Subbuilders
        # and data_elements have no inheritance, so the call returns
        # the empty list naturally.
        form = raw_items[k]
        return _parse_inherits_from(form.get("inherits_from"))

    ordered = _topological_sort(insertion_order, get_deps)
    return {k: raw_items[k] for k in ordered}


def _class_schema_to_grammar_document(cls: type) -> dict[str, Any]:
    """Build the `builder_grammar` document for ``cls``.

    Reads ``cls._class_schema`` and returns a dict ready to be
    serialised with ``json.dumps``. Does not write to disk; the
    classmethod ``to_grammar`` on ``BuilderBase`` handles I/O.

    Sections are always present (empty dict if no entries). Top-level
    keys are emitted in this order:

    1. ``document_format``
    2. ``grammar``
    3. ``abstracts``
    4. ``elements``

    Sub-builders and data-elements are ordinary elements marked in their
    ``_meta`` (``subbuilder`` / ``data_element``, plus ``render_tag`` /
    ``render_attributes`` for a boundary envelope), so they appear in the
    ``elements`` section with that ``_meta`` — no separate section.
    Both forms of ``subbuilder`` (registry name, ``kwarg:attr``
    parameter reference) are plain strings and pass through verbatim;
    see GRAMMAR_FORMAT.md §4 for what a consumer may do with each.

    Within each section, entries are topologically sorted by their
    ``inherits_from`` references (insertion-order on ties).
    """
    schema = cls._class_schema  # type: ignore[attr-defined]

    custom_types: dict[str, Any] = {}
    abstracts_raw: dict[str, dict[str, Any]] = {}
    abstracts_order: list[str] = []
    abstracts_bag = schema["_abstracts"]
    for node in abstracts_bag:
        abstracts_raw[node.label] = _abstract_form(node, custom_types)
        abstracts_order.append(node.label)

    elements_raw: dict[str, dict[str, Any]] = {}
    elements_order: list[str] = []
    for node in schema.get_nodes(
        condition=lambda n: not n.label.startswith("_")
    ):
        elements_raw[node.label] = _element_form(node, custom_types)
        elements_order.append(node.label)

    document: dict[str, Any] = {
        "document_format": {
            "name": FORMAT_NAME,
            "version": FORMAT_VERSION,
        },
        "grammar": {
            "name": cls._name,  # type: ignore[attr-defined]
            "version": None,
            "title": None,
            "description": None,
        },
        "abstracts": _section_topologically_sorted(
            abstracts_raw, abstracts_order
        ),
        "elements": _section_topologically_sorted(
            elements_raw, elements_order
        ),
    }
    if custom_types:
        document["document_format"]["version"] = CUSTOM_TYPES_FORMAT_VERSION
        document["custom_types"] = custom_types
    return document
