# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Read a `builder_grammar` v1.1 document into schema declarations.

The **consumer** side of the format specified in ``GRAMMAR_FORMAT.md``.
``BuilderBase.__init_subclass__`` calls :func:`_read_grammar_document`
for each document named in a class's ``_grammar_documents`` and writes
the returned declarations into ``_class_schema``, with the same node
attributes a decorated ``@element`` / ``@abstract`` produces.

The document is validated as genro-builders-js validates it
(``parseGrammarDocument`` in ``grammar-loader.js``): exact top-level
keys, format version ``1.1``, known entry keys, parameter shape.
Annotation descriptors are decoded into Python types and validators
(``Range``, ``Regex``) without importing any module named by the
document.

Exports:
    _read_grammar_document: validate a document file, return its
        abstracts and elements as schema-node attribute dicts.
"""

from __future__ import annotations

import inspect
import json
import re
import types
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, Union, get_args, get_origin

from ._grammar_export import CUSTOM_TYPES_FORMAT_VERSION, FORMAT_NAME, FORMAT_VERSION
from ._utilities import SIGNATURE_SKIP_PARAMS, _parse_sub_tags_spec, _split_annotated
from ._validators import Range, Regex
from .custom_types import CustomTypes, _CustomType

_ABSTRACT_KEYS = ("doc", "sub_tags", "parent_tags", "inherits_from", "ns", "attributes", "_meta")
_ELEMENT_KEYS = _ABSTRACT_KEYS + ("node_label", "collection_key")
_PARAM_KINDS = frozenset({
    "positional_only", "positional_or_keyword", "keyword_only",
    "var_positional", "var_keyword",
})
_PARAM_ROLES = frozenset({"framework", "value", "attribute"})
_VARIADIC_KINDS = frozenset({"var_positional", "var_keyword"})

#: Named types a document may reference. Nothing else is resolved: a
#: document never makes the loader import a module.
_SAFE_TYPES: dict[tuple[Any, Any], Any] = {
    ("builtins", "str"): str,
    ("builtins", "int"): int,
    ("builtins", "float"): float,
    ("builtins", "bool"): bool,
    ("builtins", "list"): list,
    ("builtins", "dict"): dict,
    ("builtins", "tuple"): tuple,
    ("builtins", "set"): set,
    ("builtins", "object"): object,
    ("builtins", "NoneType"): type(None),
    ("collections.abc", "Callable"): Callable,
}


def _fail(path: str, message: str) -> NoReturn:
    raise ValueError(f"{path}: {message}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    return value


def _json_copy(value: Any, path: str) -> Any:
    """Independent copy of finite JSON data (``allow_nan=False``)."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        _fail(path, f"must contain only finite JSON values ({exc})")


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Regex constructs genro-builders-js refuses (``grammar-loader.js``):
#: ``\A \Z \w \W \d \D \s \S``, ``(?P<``/``(?P=``/``(?P!``,
#: conditionals ``(?(`` and atomic groups ``(?>``.
_NON_PORTABLE_REGEX = re.compile(r"\\[AZzUwWdDsSabBN0-9]|\(\?P[<=!]|\(\?\(|\(\?>|\(\?#|\(\?[aiLmsux-]|[+*?}]\+|\{,")

_CARDINALITY_ITEM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*|\*)(?:\[(?:(\d+)|(\d*):(\d*))\])?")


def _check_sub_tags(spec: str, path: str) -> None:
    """Reject what genro-builders-js ``parseCardinality`` rejects on top of
    ``_parse_sub_tags_spec``: a repeated tag, a maximum below the minimum."""
    seen: set[str] = set()
    for raw in spec.split(","):
        match = _CARDINALITY_ITEM.fullmatch(raw.strip())
        if match is None:
            continue  # empty item, or a syntax _parse_sub_tags_spec reports
        name, exact, lower, upper = match.groups()
        if name in seen:
            _fail(path, f"duplicate tag {name!r}")
        seen.add(name)
        if exact is None and upper:
            minimum = int(lower) if lower else 0
            if int(upper) < minimum:
                _fail(path, f"maximum {upper} is below minimum {minimum} in {raw.strip()!r}")


def _accepts_none(annotation: Any) -> bool:
    """Whether an explicit ``None`` passes ``annotation`` as it passes the
    genro-builders-js test of the same descriptor: ``Any``, ``NoneType``,
    ``object``, a literal ``None``, a union with such a member, an
    ``Annotated`` whose base accepts it and whose metadata holds no
    ``Range`` / ``Regex`` (they test numbers and strings only)."""
    if annotation is None or annotation is Any or annotation is type(None) or annotation is object:
        return True
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return any(_accepts_none(arg) for arg in get_args(annotation))
    if origin is Literal:
        return None in get_args(annotation)
    if origin is Annotated:
        base, *metadata = get_args(annotation)
        return _accepts_none(base) and not any(isinstance(m, (Range, Regex, _CustomType)) for m in metadata)
    return False


def _check_parent_tags(spec: str, path: str) -> None:
    """Reject what genro-builders-js ``parseParents`` rejects.

    Each comma-separated name is an identifier, and no name repeats;
    empty items are skipped.
    """
    seen: set[str] = set()
    for raw in spec.split(","):
        name = raw.strip()
        if not name:
            continue
        if not _IDENTIFIER.fullmatch(name) or name in seen:
            _fail(path, f"invalid or duplicate parent {raw!r}")
        seen.add(name)


def _string_or_null(item: dict[str, Any], keys: tuple[str, ...], path: str) -> None:
    for key in keys:
        if item[key] is not None and type(item[key]) is not str:
            _fail(f"{path}.{key}", "must be a string or null")


def _annotation(desc: Any, path: str, custom_types: Any = None) -> Any:
    """Decode an annotation descriptor into a Python annotation."""
    if desc is None:
        return None
    item = _object(desc, path)
    kind = item.get("kind")
    if kind == "custom":
        if set(item) != {"kind", "name"} or type(item["name"]) is not str:
            _fail(path, "custom requires only kind and string name")
        if custom_types is None:
            _fail(path, "custom type references require a catalog; nested catalog references are unsupported")
        if item["name"] not in custom_types._types:
            _fail(path, f"unknown custom type {item['name']!r}")
        return custom_types._types[item["name"]]
    if kind == "any":
        return Any
    if kind == "ellipsis":
        return Ellipsis
    if kind == "type":
        key = (item.get("module"), item.get("name"))
        if key not in _SAFE_TYPES:
            _fail(path, f"unsupported named type {key[0]}.{key[1]}; implicit imports are forbidden")
        return _SAFE_TYPES[key]
    if kind == "literal":
        values = item.get("values")
        if type(values) is not list or not values:
            _fail(path, "literal values must be a non-empty array")
        return Literal[tuple(_json_copy(values, f"{path}.values"))]
    if kind == "union":
        items = item.get("items")
        if type(items) is not list or not items:
            _fail(path, "union items must be a non-empty array")
        args = tuple(_annotation(v, f"{path}.items[{i}]", custom_types) for i, v in enumerate(items))
        if None in args:
            _fail(path, "a null descriptor cannot be a union member")
        return Union[args]
    if kind == "generic":
        origin = _annotation(item.get("origin"), f"{path}.origin", custom_types)
        if origin not in (list, dict, tuple, set):
            _fail(path, "only list, dict, tuple and set generic origins are supported")
        raw_args = item.get("arguments")
        if type(raw_args) is not list:
            _fail(path, "generic arguments must be an array")
        args = tuple(_annotation(v, f"{path}.arguments[{i}]", custom_types) for i, v in enumerate(raw_args))
        if None in args:
            _fail(path, "generic arguments cannot be null")
        return origin[args[0] if len(args) == 1 else args]
    if kind == "annotated":
        base = _annotation(item.get("base"), f"{path}.base", custom_types)
        if base is None:
            _fail(path, "annotated base cannot be null")
        metadata = item.get("metadata")
        if type(metadata) is not list or not metadata:
            _fail(path, "annotated metadata must be a non-empty array")
        decoded = [_metadata(v, f"{path}.metadata[{i}]") for i, v in enumerate(metadata)]
        return Annotated[base, *decoded]
    _fail(path, f"unsupported annotation kind {kind!r}")


def _metadata(desc: Any, path: str) -> Any:
    """Decode one ``Annotated`` metadata descriptor."""
    item = _object(desc, path)
    kind = item.get("kind")
    if kind == "regex":
        pattern, flags = item.get("pattern"), item.get("flags")
        if type(pattern) is not str or type(flags) is not int or flags < 0:
            _fail(path, "regex requires a string pattern and non-negative integer flags")
        # Portability, as genro-builders-js checks it: only the flags JS
        # can reproduce, no IGNORECASE (Unicode case rules differ), no
        # construct whose meaning differs between the two engines.
        unsupported = flags & ~(2 | 8 | 16 | 32)  # IGNORECASE, MULTILINE, DOTALL, UNICODE
        if unsupported:
            _fail(path, f"unsupported Python regex flags {unsupported}")
        if flags & 2:
            _fail(path, "IGNORECASE is not portable across Python and JavaScript Unicode rules")
        if _NON_PORTABLE_REGEX.search(pattern.replace(r"[\s\S]", ".")):
            _fail(path, "regex uses a non-portable construct or character class")
        try:
            re.compile(pattern, flags)
        except re.error as exc:
            _fail(path, f"invalid regex ({exc})")
        return Regex(pattern, flags)
    if kind == "range":
        bounds = {}
        for key in ("ge", "le", "gt", "lt"):
            if key not in item:
                _fail(path, f"range missing '{key}'")
            value = item[key]
            if value is not None and type(value) not in (int, float):
                _fail(f"{path}.{key}", "must be a number or null")
            bounds[key] = value
        return Range(**bounds)
    if kind == "value":
        return _json_copy(item.get("value"), f"{path}.value")
    _fail(path, f"unsupported annotation metadata kind {kind!r}")


def _custom_types(raw: Any) -> CustomTypes:
    """Decode a catalog without imports, executable metadata or dependencies."""
    registry = CustomTypes()
    for name, definition in _object(raw, "custom_types").items():
        path = f"custom_types.{name}"
        item = _object(definition, path)
        if set(item) != {"kind", "base", "metadata"} or item["kind"] != "annotated":
            _fail(path, "custom definition must be an annotated base with one validator")
        metadata = item["metadata"]
        if (type(metadata) is not list or len(metadata) != 1
                or not isinstance(metadata[0], dict)
                or metadata[0].get("kind") not in ("regex", "range")):
            _fail(path, "custom definition requires one portable Regex or Range validator")
        base = _annotation(item["base"], f"{path}.base")
        expected = (str,) if metadata[0]["kind"] == "regex" else (int, float)
        if base not in expected:
            _fail(path, "portable Regex requires str; portable Range requires int or float")
        validator = _metadata(metadata[0], f"{path}.metadata[0]")
        registry.register(name, base, validator)
    return registry


def _signature(
    desc: dict[str, Any], path: str, *, component: bool, custom_types: Any = None,
) -> tuple[dict[str, tuple[Any, list, Any]], set[str], bool, set[str], set[str]]:
    """Compile an ``attributes`` descriptor into the schema signature keys.

    Returns ``(call_args_validations, declared_names, accepts_var_keyword,
    required_names, nullable_names)``; the first three have the meaning
    ``_extract_signature_info`` gives them. Every non-variadic,
    non-framework parameter enters ``call_args_validations`` (an
    unannotated one as ``Any``). ``required_names`` are the parameters
    without default: required by presence, as genro-builders-js requires
    them, so an explicit ``None`` is a supplied value. The first
    positional parameter of a component is its expansion root, supplied
    by the renderer, and is skipped as in genro-builders-js.
    ``nullable_names`` are the parameters whose annotation accepts an
    explicit ``None`` (``_accepts_none``).
    """
    unknown = set(desc) - {"parameters", "accepts_var_keyword", "accepts_var_positional"}
    if unknown:
        _fail(path, f"unknown fields {sorted(unknown)!r}")
    params = desc.get("parameters", [])
    if type(params) is not list:
        _fail(path, "parameters must be an array")
    params = [_object(p, f"{path}.parameters[{i}]") for i, p in enumerate(params)]
    found_var_keyword = any(p.get("kind") == "var_keyword" for p in params)
    found_var_positional = any(p.get("kind") == "var_positional" for p in params)
    if (desc.get("accepts_var_keyword", found_var_keyword) is not found_var_keyword
            or desc.get("accepts_var_positional", found_var_positional) is not found_var_positional):
        _fail(path, "variadic summary flags do not match parameters")

    component_root = None
    if component:
        component_root = next(
            (p.get("name") for p in params
             if p.get("role") != "framework"
             and p.get("kind") in ("positional_only", "positional_or_keyword")),
            None,
        )

    validations: dict[str, tuple[Any, list, Any]] = {}
    declared: set[str] = set()
    required_names: set[str] = set()
    nullable_names: set[str] = set()
    seen: set[str] = set()
    required = {"name", "kind", "role", "annotation", "has_default"}
    for index, param in enumerate(params):
        ppath = f"{path}.parameters[{index}]"
        if not required <= set(param) or set(param) - (required | {"default"}):
            _fail(ppath, "invalid parameter shape")
        name, kind, role = param["name"], param["kind"], param["role"]
        if type(name) is not str or not name.isidentifier() or name in seen:
            _fail(f"{ppath}.name", "invalid or duplicate parameter name")
        seen.add(name)
        if kind not in _PARAM_KINDS or role not in _PARAM_ROLES:
            _fail(ppath, "invalid kind or role")
        if type(param["has_default"]) is not bool or ("default" in param) is not param["has_default"]:
            _fail(ppath, "default presence must equal has_default")
        if role == "framework" and name not in SIGNATURE_SKIP_PARAMS:
            _fail(ppath, f"unknown framework parameter {name!r}")
        if role == "value" and name != "node_value":
            _fail(ppath, "the value role is reserved for node_value")
        annotation = _annotation(param["annotation"], f"{ppath}.annotation", custom_types)
        if kind in _VARIADIC_KINDS or role == "framework" or name == component_root:
            continue
        declared.add(name)
        base, validators = _split_annotated(Any if annotation is None else annotation)
        if _accepts_none(annotation):
            nullable_names.add(name)
        if param["has_default"]:
            default = _json_copy(param["default"], f"{ppath}.default")
        else:
            default = inspect.Parameter.empty
            required_names.add(name)
        validations[name] = (base, validators, default)
    return validations, declared, found_var_keyword, required_names, nullable_names


def _declaration(raw: Any, path: str, *, is_element: bool, custom_types: Any = None) -> dict[str, Any]:
    """Validate one entry and return its schema-node attributes."""
    keys = _ELEMENT_KEYS if is_element else _ABSTRACT_KEYS
    item = _object(raw, path)
    unknown = set(item) - set(keys)
    if unknown:
        _fail(path, f"unknown fields {sorted(unknown)!r}")
    item = {**dict.fromkeys(keys), **item}
    _string_or_null(item, ("doc", "sub_tags", "parent_tags", "inherits_from", "ns"), path)
    if item["_meta"] is not None:
        _object(item["_meta"], f"{path}._meta")
    if item["sub_tags"] is not None:
        _parse_sub_tags_spec(item["sub_tags"])
        _check_sub_tags(item["sub_tags"], f"{path}.sub_tags")
    if item["parent_tags"] is not None:
        _check_parent_tags(item["parent_tags"], f"{path}.parent_tags")
    attributes = item["attributes"]
    if attributes is not None:
        _object(attributes, f"{path}.attributes")
    attrs: dict[str, Any] = {
        "sub_tags": item["sub_tags"],
        "parent_tags": item["parent_tags"],
        "inherits_from": item["inherits_from"] or "",
        "_meta": _json_copy(item["_meta"], f"{path}._meta"),
        "documentation": item["doc"],
        "attributes": _json_copy(attributes, f"{path}.attributes"),
    }
    if item["ns"] is not None:
        attrs["ns"] = item["ns"]
    if not is_element:
        if attributes is not None:
            _signature(attributes, f"{path}.attributes", component=False, custom_types=custom_types)
        return attrs
    _string_or_null(item, ("node_label", "collection_key"), path)
    attrs["node_label"] = item["node_label"]
    attrs["collection_key"] = item["collection_key"]
    if attributes is not None:
        validations, declared, accepts_var_keyword, required_names, nullable_names = _signature(
            attributes, f"{path}.attributes",
            component=bool((item["_meta"] or {}).get("component")), custom_types=custom_types,
        )
        attrs["call_args_validations"] = validations
        attrs["declared_names"] = declared
        attrs["accepts_var_keyword"] = accepts_var_keyword
        # A signature read from a document follows the genro-builders-js
        # contract in ``_validate_call_args``: required by presence, and
        # JSON primitives kept apart (``True`` is not an int).
        attrs["loaded_required_names"] = required_names
        attrs["loaded_nullable_names"] = nullable_names
        attrs["loaded_strict_json_primitives"] = True
    return attrs


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"non-finite number {name} is not JSON")


def _read_grammar_document(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate the v1.1 document at ``path``; return its declarations.

    Returns ``(abstracts, elements)``: name -> schema-node attributes,
    in document order. Raises ``ValueError`` naming the file and the
    offending field.
    """
    document = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    try:
        return _declarations(document)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None


def _declarations(
    document: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    root = _object(document, "document")
    required = {"document_format", "grammar", "abstracts", "elements"}
    if not required <= set(root) or set(root) - (required | {"custom_types"}):
        _fail("document", "must contain exactly document_format, grammar, abstracts and elements")
    if root["document_format"] not in (
        {"name": FORMAT_NAME, "version": FORMAT_VERSION},
        {"name": FORMAT_NAME, "version": CUSTOM_TYPES_FORMAT_VERSION},
    ):
        _fail("document_format", f"expected {FORMAT_NAME} version 1.1 or 1.2")
    if "custom_types" in root and root["document_format"]["version"] != CUSTOM_TYPES_FORMAT_VERSION:
        _fail("document_format", "custom_types requires version 1.2")
    catalog = _json_copy(root.get("custom_types", {}), "custom_types")
    custom_types = _custom_types(catalog)
    grammar = _object(root["grammar"], "grammar")
    if set(grammar) != {"name", "version", "title", "description"}:
        _fail("grammar", "must contain exactly name, version, title and description")
    if type(grammar["name"]) is not str or not grammar["name"]:
        _fail("grammar.name", "must be a non-empty string")
    _string_or_null(grammar, ("version", "title", "description"), "grammar")
    sections = []
    for section, is_element in (("abstracts", False), ("elements", True)):
        entries = _object(root[section], section)
        declarations = {}
        for name, raw in entries.items():
            if not name or name.startswith("_"):
                _fail(section, f"invalid public name {name!r}")
            declarations[name] = _declaration(raw, f"{section}.{name}", is_element=is_element, custom_types=custom_types)
            if catalog:
                declarations[name]["custom_types"] = catalog
        sections.append(declarations)
    return sections[0], sections[1]
