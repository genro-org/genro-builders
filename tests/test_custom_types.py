# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Named input constraints retain their identity across the grammar wire."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import get_args

import pytest

from genro_builders import BuilderBase, CustomTypes, SourceBag
from genro_builders.builder import Range, Regex, element
from genro_builders.builder._grammar_export import _class_schema_to_grammar_document

ct = CustomTypes()
ct.register("no_pointer", str, Regex(r"(?![\^=])[\s\S]*"))
ct.register("code", str, Regex(r"[A-Z]{2}[0-9]{4}"))
ct.register("positive", int, Range(ge=1))


class ContactBuilder(BuilderBase):
    _name = "custom_types_contract"

    @element()
    def contact(self, method: ct.no_pointer, code: ct.code, record_id: str = ""): ...

    @element()
    def count(self, node_value: ct.positive): ...

    @element()
    def optional(self, method: ct.no_pointer | None = None): ...

    @element()
    def codes(self, values: list[ct.code]): ...


def load(tmp_path, document=None):
    path = tmp_path / "custom_types.json"
    path.write_text(json.dumps(document or _class_schema_to_grammar_document(ContactBuilder)))
    return type("LoadedContact", (BuilderBase,), {"_grammar_documents": (str(path),)})


def test_registry_retains_identity_and_exports_independent_data():
    assert get_args(ct.code)[0] is str
    restored = CustomTypes.from_dict(ct.to_dict())
    assert restored.to_dict() == ct.to_dict()
    restored.validate("code", "AB1234")
    with pytest.raises(ValueError, match="code"):
        restored.validate("code", "bad")
    catalog = ct.to_dict()
    catalog["code"]["metadata"][0]["pattern"] = ".*"
    with pytest.raises(ValueError):
        ct.validate("code", "bad")
    assert get_args(ct.code)[-1].name != get_args(ct.no_pointer)[-1].name


@pytest.mark.parametrize("name", ["register", "toJSON", "resolve", "to_dict", "class", "_hidden", "bad-name", "", 1])
def test_reserved_or_invalid_names(name):
    with pytest.raises(ValueError, match="name"):
        CustomTypes().register(name, str, Regex(".*"))


def test_duplicate_and_unknown_names():
    registry = CustomTypes()
    registry.register("code", str, Regex(".*"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register("code", str, Regex(".*"))
    with pytest.raises(AttributeError, match="unknown custom type"):
        registry.missing
    with pytest.raises(AttributeError):
        registry.code = str


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("method", ["", "details", "multi\nline", "😀", "inside^=", "\n=second line"])
def test_literal_strings_and_permitted_pointer_resolution(tmp_path, loaded, method):
    builder = (load(tmp_path) if loaded else ContactBuilder)()
    builder.data["record_id"] = 42
    for prefix in ("^", "="):
        node = builder.source.contact(method=method, code="AB1234", record_id=prefix + "record_id")
        _, attrs = builder.runtime_values(node)
        assert attrs["record_id"] == 42
        assert attrs["method"] == method


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("method", ["^method", "=method", "==method", "^", "="])
def test_forbidden_pointers_rejected_at_creation(tmp_path, loaded, method):
    builder = (load(tmp_path) if loaded else ContactBuilder)()
    with pytest.raises(ValueError, match="no_pointer"):
        builder.source.contact(method=method, code="AB1234")
    assert len(builder.source) == 0


@pytest.mark.parametrize("method", ["^method", "=method", "==method"])
@pytest.mark.parametrize("serialized", [False, True])
def test_raw_source_checked_before_resolution_and_pointer_discovery(tmp_path, method, serialized):
    builder = load(tmp_path)()
    node = builder.source.contact(method="details", code="AB1234", record_id="^record_id")
    node.set_attr(method=method)
    if serialized:
        source = SourceBag.from_tytx(builder.source.to_tytx())
        source._builder = builder
        source.set_backref()
        builder.source = source
        node = source.get_nodes()[0]
    for consume in (lambda: builder.runtime_values(node), node.pointers, builder.validate_source):
        with pytest.raises(ValueError, match="no_pointer"):
            consume()


@pytest.mark.parametrize("loaded", [False, True])
def test_optional_nested_and_nonstring_constraints(tmp_path, loaded):
    builder = (load(tmp_path) if loaded else ContactBuilder)()
    builder.source.optional()
    builder.source.optional(method=None)
    builder.source.codes(values=["AB1234"])
    builder.source.count(1)
    with pytest.raises(ValueError):
        builder.source.codes(values=["bad"])
    for value in (0, True):
        with pytest.raises(ValueError):
            builder.source.count(value)


def test_named_roundtrip_and_shared_fixture(tmp_path):
    document = _class_schema_to_grammar_document(ContactBuilder)
    assert document["document_format"]["version"] == "1.2"
    parameter = document["elements"]["contact"]["attributes"]["parameters"][0]
    assert parameter["annotation"] == {"kind": "custom", "name": "no_pointer"}
    assert document["custom_types"] == ct.to_dict()
    roundtrip = _class_schema_to_grammar_document(load(tmp_path, document))
    assert roundtrip["custom_types"] == document["custom_types"]
    assert roundtrip["elements"]["contact"] == document["elements"]["contact"]
    fixture = Path(__file__).parent / "fixtures" / "custom_types.json"
    assert document == json.loads(fixture.read_text())


def test_unknown_reference_and_legacy_version_rejected(tmp_path):
    document = _class_schema_to_grammar_document(ContactBuilder)
    del document["custom_types"]["no_pointer"]
    with pytest.raises(ValueError, match="unknown custom type"):
        load(tmp_path, document)
    document = _class_schema_to_grammar_document(ContactBuilder)
    document["document_format"]["version"] = "1.1"
    with pytest.raises(ValueError, match="requires version 1.2"):
        load(tmp_path, document)


@pytest.mark.parametrize("validator", [Regex(r"\w+"), Regex("abc", 2),
                                     Regex(r"\bélan\b"), Regex("(?i:abc)"),
                                     Regex("a++"), Regex(r"(a)?\1"), lambda value: None])
def test_nonportable_validators_rejected_on_export(validator):
    registry = CustomTypes()
    registry.register("local", str, validator)
    with pytest.raises((TypeError, ValueError), match="portable|callable"):
        registry.to_dict()


def test_conflicting_catalogs_rejected_during_composition(tmp_path):
    original = _class_schema_to_grammar_document(ContactBuilder)
    changed = deepcopy(original)
    changed["custom_types"]["code"]["metadata"][0]["pattern"] = "[0-9]+"
    changed["elements"] = {"other": changed["elements"]["contact"]}
    first = load(tmp_path, original)
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="conflicting custom type"):
        type("Combined", (first,), {"_grammar_documents": (str(path),)})


def test_subbuilder_envelope_keeps_its_host_constraint():
    class Inner(BuilderBase):
        _name = "custom_types_inner"

    class Host(BuilderBase):
        @element(sub_tags="*", _meta={"subbuilder": "custom_types_inner"})
        def mount(self, method: ct.no_pointer): ...

    builder = Host()
    node = builder.source.mount(method="details")
    assert isinstance(node.builder, Inner)
    node.set_attr(method="^method")
    for consume in (lambda: builder.runtime_values(node), node.pointers, builder.validate_source):
        with pytest.raises(ValueError, match="no_pointer"):
            consume()


def test_nested_optional_registered_types():
    class OptionalItems(BuilderBase):
        @element()
        def items(self, values: list[ct.code | None]): ...

    builder = OptionalItems()
    node = builder.source.items(values=[None, "AB1234"])
    builder.runtime_values(node)
    with pytest.raises(ValueError):
        builder.source.items(values=[None, "invalid"])


def test_registered_null_input_is_rejected_when_not_nullable():
    builder = ContactBuilder()
    node = builder.source.contact(method="details", code="AB1234")
    node.set_attr(method=None, _remove_null_attributes=False)
    with pytest.raises(ValueError):
        builder.runtime_values(node)


@pytest.mark.parametrize(("pattern", "flags", "value", "expected"), [
    (".+", 0, "\r", True), (".+", 0, "\u2028", True), (".+", 0, "\u2029", True),
    (".+", 0, "\n", False), (".+", 16, "\n", True),
    (r"a$\r", 0, "a\r", False), (r"a$\n", 0, "a\n", True),
    (r"a$\r", 8, "a\r", False), (r"a$\nb", 8, "a\nb", True),
    (r"a\n^b", 8, "a\nb", True), (r"a\r^b", 8, "a\rb", False),
    ("[.$^]+", 0, ".$^", True), (r"\.+", 0, "...", True),
    ("AB[0-9]+", 0, "AB12\n", False),
])
def test_portable_regex_line_boundaries(pattern, flags, value, expected):
    registry = CustomTypes()
    registry.register("pattern", str, Regex(pattern, flags))
    restored = CustomTypes.from_dict(registry.to_dict())
    if expected:
        restored.validate("pattern", value)
    else:
        with pytest.raises(ValueError):
            restored.validate("pattern", value)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_registered_numbers_use_finite_json_domain(value):
    registry = CustomTypes()
    registry.register("number", float, Range())
    with pytest.raises(TypeError, match="finite"):
        registry.validate("number", value)
