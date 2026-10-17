# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Tests for BuilderBase.to_grammar — the builder_grammar v1.1 exporter.

The format specification lives in
``src/genro_builders/builder/GRAMMAR_FORMAT.md``.

These tests exercise the export end-to-end on real dialects (HTML,
SVG, CSS) and on small ad-hoc builders that reproduce specific
edge cases (missing inherits_from target, topological order).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genro_builders import BuilderBase
from genro_builders.builder import abstract, element
from genro_builders.builder._grammar_export import (
    _class_schema_to_grammar_document,
)
from genro_builders.contrib.css import CssBuilder
from genro_builders.contrib.html import HtmlBuilder
from genro_builders.contrib.svg import SvgBuilder


def _dump(cls: type, tmp_path: Path) -> dict:
    out = tmp_path / f"{cls._name}.json"
    cls.to_grammar(out)
    return json.loads(out.read_text())


# ---------------------------------------------------------------------------
# Happy path on real dialects
# ---------------------------------------------------------------------------


def test_html_grammar_export(tmp_path: Path) -> None:
    data = _dump(HtmlBuilder, tmp_path)

    assert data["document_format"]["name"] == "builder_grammar"
    assert data["document_format"]["version"] == "1.1"
    assert data["grammar"]["name"] == "html"

    assert "div" in data["elements"]
    assert data["elements"]["div"]["sub_tags"]
    assert data["elements"]["br"]["sub_tags"] == ""

    # Sub-builders are ordinary elements marked in their ``_meta``.
    assert "svg" in data["elements"]
    assert data["elements"]["svg"]["_meta"]["subbuilder"] == "svg"


def test_svg_grammar_export_emits_bare_abstract_names(tmp_path: Path) -> None:
    data = _dump(SvgBuilder, tmp_path)

    assert data["grammar"]["name"] == "svg"
    assert "graphics" in data["abstracts"]
    assert "containerElement" in data["abstracts"]

    # Bare labels — no `@` prefix anywhere in the exported JSON
    raw = json.dumps(data)
    assert "@graphics" not in raw
    assert "@containerElement" not in raw


def test_svg_grammar_export_includes_html_subbuilder_with_render_tag(tmp_path: Path) -> None:
    """The ``html`` sub-builder is an element whose ``_meta`` carries the
    dialect switch and the boundary envelope (foreignObject + xmlns)."""
    data = _dump(SvgBuilder, tmp_path)

    meta = data["elements"]["html"]["_meta"]
    assert meta["subbuilder"] == "html"
    assert meta["render_tag"] == "foreignObject"
    assert meta["render_attributes"] == {
        "xmlns": "http://www.w3.org/1999/xhtml",
    }


def test_parameter_reference_subbuilder_exports_verbatim() -> None:
    """The ``kwarg:attr`` form is a plain string: the export stays valid
    JSON and the reference is preserved verbatim (no reconstruction
    promise — GRAMMAR_FORMAT §4)."""

    class _AppsHost(BuilderBase):
        _name = None  # not registered

        @element(sub_tags="application")
        def apps(self, **kwargs): ...

        @element(_meta={"subbuilder": "app:grammar"})
        def application(self, code=None, app=None): ...

    data = json.loads(json.dumps(_class_schema_to_grammar_document(_AppsHost)))
    assert data["elements"]["application"]["_meta"]["subbuilder"] == "app:grammar"


def test_css_grammar_export_smoke(tmp_path: Path) -> None:
    data = _dump(CssBuilder, tmp_path)

    assert data["grammar"]["name"] == "css"
    assert isinstance(data["elements"], dict)
    assert len(data["elements"]) > 0


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_document_format_is_first_key(tmp_path: Path) -> None:
    data = _dump(HtmlBuilder, tmp_path)
    assert next(iter(data)) == "document_format"


def test_sections_are_always_present_in_usage_order(tmp_path: Path) -> None:
    """Sub-builders and data-elements are ordinary elements (marked in
    ``_meta``), so the document has just ``abstracts`` then ``elements``."""
    data = _dump(HtmlBuilder, tmp_path)

    for section in ("abstracts", "elements"):
        assert section in data
        assert isinstance(data[section], dict)

    keys = list(data.keys())
    assert keys.index("abstracts") < keys.index("elements")
    assert "subbuilders" not in data
    assert "data_elements" not in data


def test_no_at_prefix_in_labels_or_inherits_from(tmp_path: Path) -> None:
    """Sentinel: no `@` prefix in any label (top-level or abstract) and
    in any `inherits_from` value. Catches accidental leakage of the
    old abstract-prefix convention.

    Note: `@` is allowed inside free-form `doc` strings (e.g. the CSS
    grammar legitimately discusses `@import` / `@media` / `@supports`
    in element documentation). The sentinel scopes itself to the
    structural fields where `@` would denote the old convention.
    """
    for cls in (HtmlBuilder, SvgBuilder, CssBuilder):
        data = _dump(cls, tmp_path)

        # No `@` in any label key, in any section.
        for section_name in ("abstracts", "elements"):
            for label in data[section_name]:
                assert "@" not in label, (
                    f"{cls.__name__}: label {label!r} in section "
                    f"{section_name!r} contains '@'"
                )

        # No `@` in any `inherits_from` value.
        for section_name in ("abstracts", "elements"):
            for label, form in data[section_name].items():
                value = form.get("inherits_from")
                if value is not None:
                    assert "@" not in value, (
                        f"{cls.__name__}: {section_name}.{label}."
                        f"inherits_from={value!r} contains '@'"
                    )


# ---------------------------------------------------------------------------
# Validation: dangling inherits_from raises at class-definition time
# ---------------------------------------------------------------------------


def test_inherits_from_unknown_raises_value_error() -> None:
    """Declaring `inherits_from` against a non-existent abstract must
    fail loudly at class-definition time (no silent fallback at
    runtime)."""

    with pytest.raises(ValueError, match="inherits_from"):
        class _Bogus(BuilderBase):
            _name = None  # not registered

            @abstract(sub_tags="span,a")
            def phrasing(self, **kwargs): ...

            @element(inherits_from="ghost")
            def p(self, **kwargs): ...


def test_inherits_from_partial_unknown_in_list_raises() -> None:
    """A typo in any name of a comma-separated `inherits_from` list
    must raise — even if the other names resolve correctly."""

    with pytest.raises(ValueError, match="inherits_from"):
        class _Bogus(BuilderBase):
            _name = None

            @abstract(sub_tags="span")
            def phrasing(self, **kwargs): ...

            @element(inherits_from="phrasing,ghost")
            def p(self, **kwargs): ...


# ---------------------------------------------------------------------------
# Topological ordering within a section
# ---------------------------------------------------------------------------


def test_abstracts_section_is_topologically_ordered() -> None:
    """An abstract that inherits from another must appear after its
    parent in the abstracts section."""

    class _Topo(BuilderBase):
        _name = None  # not registered

        @abstract(sub_tags="a,b,c")
        def base_phrasing(self, **kwargs): ...

        # Declared *before* base_phrasing in source order but must
        # come *after* in the exported document.
        @abstract(sub_tags="d,e,f", inherits_from="base_phrasing")
        def extended_phrasing(self, **kwargs): ...

    document = _Topo.__mro__[0]  # ensure class is built

    # Build the document directly to avoid touching the filesystem
    data = _class_schema_to_grammar_document(_Topo)
    abstracts_keys = list(data["abstracts"].keys())

    assert "base_phrasing" in abstracts_keys
    assert "extended_phrasing" in abstracts_keys
    assert abstracts_keys.index("base_phrasing") < abstracts_keys.index(
        "extended_phrasing"
    ), abstracts_keys
    del document  # silence unused-var warning


def test_unrecognized_sub_tags_item_raises_at_class_definition():
    import pytest

    from genro_builders.builder import BuilderBase, element

    with pytest.raises(ValueError, match="unrecognized sub_tags item"):
        class Broken(BuilderBase):
            @element(sub_tags="div [1]")
            def box(self, **kwargs): ...


# ---------------------------------------------------------------------------
# Export 1.1: signatures, _meta and portability
# ---------------------------------------------------------------------------


def test_export_preserves_all_element_decorator_options_and_signature(tmp_path):
    from typing import Annotated, Literal
    from genro_builders.builder import Range, Regex

    # Concrete annotations avoid resolving function-local names from future annotations.
    def declaration(self, node_value=None, /, plain="default", *, count=2, mode="a", **extras): ...
    declaration.__annotations__ = {
        "node_value": Annotated[str, Regex("[A-Z]+", 2)] | None,
        "count": Annotated[int, Range(ge=1, lt=8)],
        "mode": Literal["a", "b"],
    }
    decorated = element(sub_tags="child[0:2]", parent_tags="root", node_label="stable",
                        collection_key="${code}_${env}", ns="x",
                        _meta={"render_tag": "x:item", "capabilities": ["styling"]})(declaration)

    class Dialect(BuilderBase):
        _name = None
        item = decorated

    data = _dump(Dialect, tmp_path)["elements"]["item"]
    assert data["sub_tags"] == "child[0:2]"
    assert data["parent_tags"] == "root"
    assert data["node_label"] == "stable"
    assert data["collection_key"] == "${code}_${env}"
    assert data["ns"] == "x"
    assert data["_meta"] == {"render_tag": "x:item", "capabilities": ["styling"]}
    attrs = data["attributes"]
    assert attrs["accepts_var_keyword"] is True
    params = {p["name"]: p for p in attrs["parameters"]}
    assert list(params) == ["node_value", "plain", "count", "mode", "extras"]
    assert params["node_value"]["kind"] == "positional_only"
    assert params["node_value"]["role"] == "value"
    assert params["node_value"]["annotation"]["kind"] == "union"
    assert params["node_value"]["annotation"]["items"][0]["metadata"] == [
        {"kind": "regex", "pattern": "[A-Z]+", "flags": 2}]
    assert params["plain"]["default"] == "default"
    assert params["plain"]["annotation"] is None
    assert params["count"]["kind"] == "keyword_only"
    assert params["count"]["annotation"]["metadata"] == [
        {"kind": "range", "ge": 1, "le": None, "gt": None, "lt": 8}]
    assert params["mode"]["annotation"] == {"kind": "literal", "values": ["a", "b"]}


def test_closed_signature_required_and_null_default_are_distinct(tmp_path):
    class Dialect(BuilderBase):
        _name = None

        @element()
        def item(self, required, optional=None): ...

    attrs = _dump(Dialect, tmp_path)["elements"]["item"]["attributes"]
    assert attrs["accepts_var_keyword"] is False
    assert attrs["parameters"][0]["has_default"] is False
    assert "default" not in attrs["parameters"][0]
    assert attrs["parameters"][1]["has_default"] is True
    assert attrs["parameters"][1]["default"] is None


def test_abstract_signature_and_inherited_element_survive_export(tmp_path):
    class Parent(BuilderBase):
        _name = None

        @abstract(sub_tags="*", ns="x")
        def common(self, plain=3): ...

        @element(inherits_from="common", node_label="stable")
        def item(self, enabled=True): ...

    class Child(Parent):
        _name = None

    doc = _dump(Child, tmp_path)
    assert doc["abstracts"]["common"]["attributes"]["parameters"][0]["default"] == 3
    assert doc["elements"]["item"]["node_label"] == "stable"
    assert doc["elements"]["item"]["inherits_from"] == "common"


@pytest.mark.parametrize("bad", [object(), float("nan"), (1, 2), {1: "lost-key-type"}])
def test_unportable_default_fails_without_overwriting_file(tmp_path, bad):
    class Dialect(BuilderBase):
        _name = None

        @element()
        def item(self, value=bad): ...

    out = tmp_path / "grammar.json"
    out.write_text("previous")
    with pytest.raises(TypeError, match="losslessly"):
        Dialect.to_grammar(out)
    assert out.read_text() == "previous"


@pytest.mark.parametrize("bad", [object(), float("inf"), (1, 2)])
def test_unportable_meta_fails_without_overwriting_file(tmp_path, bad):
    class Dialect(BuilderBase):
        _name = None

        @element(_meta={"marker": bad})
        def item(self, **kwargs): ...

    out = tmp_path / "grammar.json"
    out.write_text("previous")
    with pytest.raises(TypeError, match="losslessly"):
        Dialect.to_grammar(out)
    assert out.read_text() == "previous"


def test_empty_meta_is_exported_as_an_empty_object(tmp_path):
    class Dialect(BuilderBase):
        _name = None

        @element(_meta={})
        def item(self, **kwargs): ...

        @element()
        def plain(self, **kwargs): ...

    elements = _dump(Dialect, tmp_path)["elements"]
    assert elements["item"]["_meta"] == {}
    assert elements["plain"]["_meta"] is None


def test_custom_callable_validator_is_not_silently_dropped(tmp_path):
    from typing import Annotated

    def declaration(self, value): ...
    declaration.__annotations__ = {"value": Annotated[str, lambda value: None]}

    class Dialect(BuilderBase):
        _name = None
        item = element()(declaration)

    with pytest.raises(TypeError, match="portable validator"):
        _dump(Dialect, tmp_path)


def test_domain_annotations_export_portable_tytx_dtypes():
    from datetime import date, datetime, time
    from decimal import Decimal
    from genro_builders.builder._grammar_export import _annotation_form
    # Built-in primitives retain the existing descriptor; registered domain
    # classes cross language boundaries through their TYTX identity.
    for cls, code in ((date, "D"), (time, "H"), (datetime, "DHZ"), (Decimal, "N")):
        assert _annotation_form(cls, 'test') == {"kind": "dtype", "dtype": code}
