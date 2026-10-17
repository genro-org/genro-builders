# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Loading ``builder_grammar`` 1.1 documents through ``_grammar_documents``.

The validations follow genro-builders-js 0.3.1 (``grammar-loader.js``):
a required parameter is required by presence, JSON ``true`` is not a
number, ``_meta`` and defaults are finite JSON, abstract chains have no
cycle, ``parent_tags`` names are identifiers without duplicates.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import json
from copy import deepcopy
from pathlib import Path

import pytest

from genro_builders import BuilderBase
from genro_builders.builder import abstract
from genro_builders.contrib.css import CssBuilder
from genro_builders.contrib.html import HtmlBuilder
from genro_builders.contrib.svg import SvgBuilder


def _document(name: str = "future") -> dict:
    return {
        "document_format": {"name": "builder_grammar", "version": "1.1"},
        "grammar": {"name": name, "version": None, "title": None, "description": None},
        "abstracts": {
            "content": {
                "doc": None, "sub_tags": "item", "parent_tags": None,
                "inherits_from": None, "ns": None, "attributes": None, "_meta": None,
            }
        },
        "elements": {
            "catalog": {
                "doc": None, "sub_tags": "item[1:]", "parent_tags": None,
                "inherits_from": "content", "ns": None,
                "attributes": {"parameters": [], "accepts_var_keyword": False,
                               "accepts_var_positional": False},
                "node_label": None, "collection_key": "${sku}", "_meta": None,
            },
            "item": {
                "doc": None, "sub_tags": "", "parent_tags": "catalog",
                "inherits_from": None, "ns": None,
                "attributes": {
                    "parameters": [
                        {"name": "sku", "kind": "positional_or_keyword", "role": "attribute",
                         "annotation": {"kind": "annotated", "base": {"kind": "type", "module": "builtins", "name": "str"},
                                        "metadata": [{"kind": "regex", "pattern": "[A-Z][0-9]+", "flags": 0}]},
                         "has_default": False},
                        {"name": "quantity", "kind": "keyword_only", "role": "attribute",
                         "annotation": {"kind": "annotated", "base": {"kind": "type", "module": "builtins", "name": "int"},
                                        "metadata": [{"kind": "range", "ge": 1, "le": None, "gt": None, "lt": None}]},
                         "has_default": True, "default": 1},
                    ],
                    "accepts_var_keyword": False, "accepts_var_positional": False,
                },
                "node_label": "entry", "collection_key": None, "_meta": None,
            },
        },
    }


def _builder_class(tmp_path: Path, document: dict | str, name: str = "grammar") -> type:
    """A BuilderBase subclass whose only document is ``document``."""
    path = tmp_path / f"{name}.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return type(f"Loaded_{name}", (BuilderBase,), {"_grammar_documents": (str(path),)})


def _item_parameter(document: dict, index: int) -> dict:
    return document["elements"]["item"]["attributes"]["parameters"][index]


@pytest.mark.parametrize(("cls", "representative"), [
    (HtmlBuilder, "div"), (SvgBuilder, "circle"), (CssBuilder, "stylesheet"),
])
def test_real_exported_collections_load(tmp_path: Path, cls: type, representative: str) -> None:
    exported = tmp_path / "exported.json"
    cls.to_grammar(exported)
    loaded = type("Loaded", (BuilderBase,), {"_grammar_documents": (str(exported),)})
    assert representative in loaded()


def test_document_uses_existing_creation_and_validation_path(tmp_path: Path) -> None:
    builder = _builder_class(tmp_path, _document())()
    root = builder.new_root()
    catalog = root.catalog()

    with pytest.raises(ValueError, match="required attribute 'sku'"):
        catalog.item()
    with pytest.raises(ValueError, match="must match pattern"):
        catalog.item(sku="bad")
    with pytest.raises(ValueError, match="must be >= 1"):
        catalog.item(sku="A1", quantity=0)
    with pytest.raises(ValueError, match="expected <class 'int'>, got bool"):
        catalog.item(sku="A1", quantity=True)
    item = catalog.item(sku="A1")
    assert item.label == "A1"
    assert builder._get_schema_info("item")["node_label"] == "entry"
    assert builder._get_schema_info("catalog")["collection_key"] == "${sku}"
    with pytest.raises(ValueError, match="parent_tags requires"):
        root.item(sku="A2")
    with pytest.raises(ValueError, match="duplicate collection key"):
        catalog.item(sku="A1")


def test_required_unannotated_and_explicit_null_follow_loaded_contract(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 0)["annotation"] = None
    catalog = _builder_class(tmp_path, document, "unannotated")().new_root().catalog()

    with pytest.raises(ValueError, match="required attribute 'sku'"):
        catalog.item()
    # An explicit None is a supplied value: the required check passes and
    # the collection key is what refuses it.
    with pytest.raises(ValueError, match="collection key needs attribute"):
        catalog.item(sku=None)
    assert catalog.item(sku=42).label == "42"

    nullable = _document("nullable")
    _item_parameter(nullable, 0)["annotation"] = {"kind": "union", "items": [
        {"kind": "type", "module": "builtins", "name": "str"},
        {"kind": "type", "module": "builtins", "name": "NoneType"},
    ]}
    nullable["elements"]["catalog"]["collection_key"] = None
    nullable_catalog = _builder_class(tmp_path, nullable, "nullable")().new_root().catalog()
    assert nullable_catalog.item(sku=None).node_tag == "item"


def test_explicit_null_is_checked_against_a_non_nullable_annotation(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 0)["annotation"] = {"kind": "type", "module": "builtins", "name": "str"}
    document["elements"]["catalog"]["collection_key"] = None
    catalog = _builder_class(tmp_path, document)().new_root().catalog()
    with pytest.raises(ValueError, match="expected <class 'str'>, got NoneType"):
        catalog.item(sku=None)


def test_loaded_float_rejects_boolean_but_keeps_python_numeric_widening(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 1)["annotation"] = {"kind": "type", "module": "builtins", "name": "float"}
    catalog = _builder_class(tmp_path, document)().new_root().catalog()

    with pytest.raises(ValueError, match="expected <class 'float'>, got bool"):
        catalog.item(sku="A1", quantity=True)
    assert catalog.item(sku="A2", quantity=2).node_tag == "item"


def test_decorated_int_still_accepts_bool() -> None:
    from genro_builders.builder import element

    class Decorated(BuilderBase):
        @element()
        def item(self, quantity: int = 1): ...

    Decorated().new_root().item(quantity=True)


def test_loader_rejects_implicit_named_type_imports(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 0)["annotation"] = {
        "kind": "type", "module": "application.models", "name": "Sku"
    }
    with pytest.raises(ValueError, match="implicit imports are forbidden"):
        _builder_class(tmp_path, document)


def test_non_finite_numbers_are_rejected(tmp_path: Path) -> None:
    text = json.dumps(_document()).replace('"_meta": null}}}', '"_meta": {"weight": NaN}}}')
    assert "NaN" in text
    with pytest.raises(ValueError, match="non-finite number NaN"):
        _builder_class(tmp_path, text)


@pytest.mark.parametrize("parent_tags", ["catalog item!", "catalog,catalog", "1catalog"])
def test_parent_tags_names_are_identifiers_without_duplicates(tmp_path: Path, parent_tags: str) -> None:
    document = _document()
    document["elements"]["item"]["parent_tags"] = parent_tags
    with pytest.raises(ValueError, match="invalid or duplicate parent"):
        _builder_class(tmp_path, document)


def test_abstract_inheritance_cycle_is_rejected(tmp_path: Path) -> None:
    document = _document()
    document["abstracts"]["base"] = dict(document["abstracts"]["content"], inherits_from="content")
    document["abstracts"]["content"]["inherits_from"] = "base"
    with pytest.raises(ValueError, match="abstract inheritance cycle"):
        _builder_class(tmp_path, document)


def test_decorated_abstract_inheritance_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="abstract inheritance cycle"):
        class Cyclic(BuilderBase):
            @abstract(sub_tags="a", inherits_from="second")
            def first(self): ...

            @abstract(sub_tags="b", inherits_from="first")
            def second(self): ...


def test_unknown_parent_of_an_abstract_is_rejected(tmp_path: Path) -> None:
    document = _document()
    document["abstracts"]["content"]["inherits_from"] = "missing"
    with pytest.raises(ValueError, match="'missing' not found among abstracts"):
        _builder_class(tmp_path, document)


def _mutations():
    def invalid_regex(d):
        _item_parameter(d, 0)["annotation"]["metadata"][0]["pattern"] = "[A-"

    def duplicate_parameter(d):
        params = d["elements"]["item"]["attributes"]["parameters"]
        params.append(deepcopy(params[0]))

    def unknown_framework(d):
        _item_parameter(d, 0)["role"] = "framework"

    def variadic_mismatch(d):
        d["elements"]["item"]["attributes"]["accepts_var_keyword"] = True

    def case_collision(d):
        d["elements"]["Item"] = deepcopy(d["elements"]["item"])

    return [
        (invalid_regex, "invalid regex"),
        (duplicate_parameter, "duplicate parameter name"),
        (unknown_framework, "unknown framework parameter"),
        (variadic_mismatch, "variadic summary flags"),
        (case_collision, "Duplicate \\(case-insensitive\\) tag"),
    ]


@pytest.mark.parametrize(("mutate", "message"), _mutations())
def test_malformed_documents_are_rejected(tmp_path: Path, mutate, message: str) -> None:
    document = _document()
    mutate(document)
    with pytest.raises(ValueError, match=message):
        _builder_class(tmp_path, document)


# ---------------------------------------------------------------------------
# Explicit None on nullable annotations (genro-builders-js union test)
# ---------------------------------------------------------------------------

_RANGED_INT = {"kind": "annotated", "base": {"kind": "type", "module": "builtins", "name": "int"},
               "metadata": [{"kind": "range", "ge": 1, "le": None, "gt": None, "lt": None}]}
_NONE_TYPE = {"kind": "type", "module": "builtins", "name": "NoneType"}


@pytest.mark.parametrize("annotation", [
    {"kind": "union", "items": [_RANGED_INT, _NONE_TYPE]},
    {"kind": "union", "items": [{"kind": "type", "module": "builtins", "name": "str"}, _NONE_TYPE]},
    {"kind": "any"},
    {"kind": "literal", "values": [1, None]},
    None,
])
def test_nullable_annotation_accepts_explicit_none(tmp_path: Path, annotation) -> None:
    document = _document()
    _item_parameter(document, 1)["annotation"] = annotation
    catalog = _builder_class(tmp_path, document)().new_root().catalog()
    assert catalog.item(sku="A1", quantity=None).node_tag == "item"


def test_nullable_ranged_int_still_validates_numbers(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 1)["annotation"] = {"kind": "union", "items": [_RANGED_INT, _NONE_TYPE]}
    catalog = _builder_class(tmp_path, document)().new_root().catalog()
    with pytest.raises(ValueError, match="must be >= 1"):
        catalog.item(sku="A1", quantity=0)
    with pytest.raises(ValueError, match="got bool"):
        catalog.item(sku="A1", quantity=True)
    assert catalog.item(sku="A1", quantity=3).node_tag == "item"


@pytest.mark.parametrize("annotation", [
    _RANGED_INT,
    {"kind": "annotated", "base": {"kind": "any"},
     "metadata": [{"kind": "range", "ge": 1, "le": None, "gt": None, "lt": None}]},
    {"kind": "literal", "values": [1, 2]},
])
def test_non_nullable_annotation_rejects_explicit_none(tmp_path: Path, annotation) -> None:
    document = _document()
    _item_parameter(document, 1)["annotation"] = annotation
    catalog = _builder_class(tmp_path, document)().new_root().catalog()
    with pytest.raises(ValueError, match="got NoneType"):
        catalog.item(sku="A1", quantity=None)


# ---------------------------------------------------------------------------
# Regex portability and sub_tags cardinality (genro-builders-js checks)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("pattern", "flags", "message"), [
    (r"\d+", 0, "non-portable construct"),
    (r"[A-Z]\w*", 0, "non-portable construct"),
    (r"(?P<code>[A-Z])", 0, "non-portable construct"),
    (r"(?>a)", 0, "non-portable construct"),
    ("[A-Z]+", 2, "IGNORECASE is not portable"),
    ("[A-Z]+", 64, "unsupported Python regex flags 64"),
    ("[A-Z]+", -1, "non-negative integer flags"),
])
def test_non_portable_regex_is_rejected(tmp_path: Path, pattern: str, flags: int, message: str) -> None:
    document = _document()
    metadata = _item_parameter(document, 0)["annotation"]["metadata"][0]
    metadata["pattern"], metadata["flags"] = pattern, flags
    with pytest.raises(ValueError, match=message):
        _builder_class(tmp_path, document)


def test_portable_regex_flags_are_accepted(tmp_path: Path) -> None:
    document = _document()
    _item_parameter(document, 0)["annotation"]["metadata"][0]["flags"] = 8 | 16 | 32
    assert "item" in _builder_class(tmp_path, document)()


@pytest.mark.parametrize(("sub_tags", "message"), [
    ("item,item", "duplicate tag 'item'"),
    ("item[2],item[0:1]", "duplicate tag 'item'"),
    ("item[3:1]", "maximum 1 is below minimum 3"),
])
def test_invalid_sub_tags_cardinality_is_rejected(tmp_path: Path, sub_tags: str, message: str) -> None:
    document = _document()
    document["elements"]["catalog"]["sub_tags"] = sub_tags
    with pytest.raises(ValueError, match=message):
        _builder_class(tmp_path, document)


def test_valid_sub_tags_cardinality_is_accepted(tmp_path: Path) -> None:
    document = _document()
    document["elements"]["catalog"]["sub_tags"] = "item[1:3],note[2],extra[:4],more[0:]"
    assert "catalog" in _builder_class(tmp_path, document)()


@pytest.mark.parametrize(("dtype", "value"), [
    ("T", "hello"), ("L", 12), ("R", 12.5), ("B", True),
    ("D", date(2026, 10, 16)),
    ("H", time(9, 30)),
    ("N", Decimal('9007199254740993.25')),
])
def test_tytx_dtype_signature_loads_without_coercing(tmp_path, dtype, value):
    doc = _document()
    doc['elements']['catalog']['collection_key'] = None
    param = _item_parameter(doc, 0)
    param['annotation'] = {'kind': 'dtype', 'dtype': dtype}
    cls = _builder_class(tmp_path, doc, 'typed')
    b = cls()
    node = b.new_root().catalog().item(sku=value)
    assert node.attr['sku'] == value
    assert type(node.attr['sku']) is type(value)


def test_unknown_dtype_is_rejected(tmp_path):
    doc = _document()
    _item_parameter(doc, 0)['annotation'] = {'kind': 'dtype', 'dtype': 'unknown'}
    with pytest.raises(ValueError, match='unknown dtype'):
        _builder_class(tmp_path, doc, 'bad_dtype')


@pytest.mark.parametrize('desc', [
    {'kind': 'dtype'}, {'kind': 'dtype', 'dtype': 1},
    {'kind': 'dtype', 'dtype': 'N', 'extra': True},
    {'kind': 'dtype', 'dtype': ''}, {'kind': 'dtype', 'dtype': 'toString'},
])
def test_malformed_dtype_is_rejected(tmp_path, desc):
    doc = _document()
    _item_parameter(doc, 0)['annotation'] = desc
    with pytest.raises(ValueError, match='dtype'):
        _builder_class(tmp_path, doc, 'bad_dtype')


@pytest.mark.parametrize(('code', 'invalid'), [
    ('L', True), ('L', 1.5), ('R', True), ('R', float('inf')),
    ('R', Decimal('1.2')),
    ('N', Decimal('NaN')),
    ('N', Decimal('Infinity')), ('N', 1.2),
    ('D', datetime(2026,10,16)), ('H','09:30'),
    ('DHZ', date(2026,10,16)), ('NN', 0),
])
@pytest.mark.parametrize('nested', ['direct', 'union', 'list'])
def test_dtype_domains_remain_strict_when_nested(tmp_path, code, invalid, nested):
    desc = {'kind':'dtype', 'dtype':code}
    if nested == 'union':
        desc = {'kind':'union', 'items':[desc, {'kind':'dtype','dtype':'NN'}]}
    elif nested == 'list':
        desc = {'kind':'generic', 'origin':{'kind':'type','module':'builtins','name':'list'}, 'arguments':[desc]}
        invalid = [invalid]
    doc = _document()
    doc['elements']['catalog']['collection_key'] = None
    _item_parameter(doc,0)['annotation'] = desc
    b = _builder_class(tmp_path,doc,'invalid_dtype')()
    with pytest.raises((TypeError,ValueError)):
        b.new_root().catalog().item(sku=invalid)


def test_dtype_nullable_and_registered_class_roundtrip(tmp_path):
    from genro_bag import Bag
    from genro_builders.builder._grammar_load import _annotation
    from genro_builders.builder._grammar_export import _annotation_form
    from genro_builders.builder._utilities import _check_type
    for code, value in [('X', Bag()), ('DH', datetime(2026,10,16)), ('NN',None)]:
        desc={'kind':'dtype','dtype':code}
        annotation = _annotation(desc,'test')
        assert _annotation_form(annotation,'test') == desc
        assert _check_type(value,annotation)
    doc=_document()
    doc['elements']['catalog']['collection_key']=None
    _item_parameter(doc,0)['annotation']={'kind':'union','items':[{'kind':'dtype','dtype':'D'}, {'kind':'dtype','dtype':'NN'}]}
    b=_builder_class(tmp_path,doc,'nullable_dtype')()
    b.new_root().catalog().item(sku=None)
