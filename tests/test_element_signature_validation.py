# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""@element call-argument validation must work from the method signature.

A declarative ``@element`` declares its accepted call arguments through
its signature (parameter names, type hints, ``Annotated`` validators).
``__init_subclass__`` reads those via ``_extract_signature_info``
into the schema's ``call_args_validations``, and ``_validate_call_args``
enforces them at call time.

Regression guard: the declarative marker returned by ``@element`` must
preserve the original signature so the extractor can read it. When the
marker dropped the function entirely, ``call_args_validations`` came out
empty and every annotated element silently skipped validation.
"""
from __future__ import annotations

from typing import Annotated

import pytest

from genro_builders.builder import BuilderBase, Regex, element


class _CountryBuilder(BuilderBase):
    _name = "test_country"
    _default_render_mode = "xml"

    @element(sub_tags="*")
    def root(self, **kwargs): ...

    @element(parent_tags="root")
    def country(
        self,
        node_value: Annotated[str, Regex("[A-Z]{2}")] | None = None,
    ): ...


def test_call_args_validations_extracted_from_signature():
    """An annotated @element must populate call_args_validations."""
    builder = _CountryBuilder()
    info = builder._get_schema_info("country")
    cav = info.get("call_args_validations")
    assert cav, "call_args_validations must not be empty for an annotated element"
    assert "node_value" in cav


def test_annotated_value_is_validated_at_call_time():
    """A value violating the element's Regex must raise at build time."""
    builder = _CountryBuilder()
    root = builder.new_root()
    node = root.root()
    with pytest.raises(ValueError, match="Validation failed"):
        node.country("XYZ")  # 3 chars violate [A-Z]{2}


def test_valid_value_passes():
    """A conforming value must not raise."""
    builder = _CountryBuilder()
    root = builder.new_root()
    node = root.root()
    node.country("IT")  # conforms to [A-Z]{2}


class _MountsBuilder(BuilderBase):
    """Closedness comes from the signature, type hints are extra.

    ``annotated`` and ``plain`` declare the same two parameters; only one
    annotates them. They must reject an undeclared attribute identically,
    and differ only in whether the declared values get type-checked.
    """

    _name = "test_mounts"
    _default_render_mode = "xml"

    @element(sub_tags="*")
    def mounts(self, **kwargs): ...

    @element(parent_tags="mounts")
    def annotated(self, *, name: str, bucket: str): ...

    @element(parent_tags="mounts")
    def plain(self, *, name, bucket): ...

    @element(parent_tags="mounts")
    def opened(self, *, name, **kwargs): ...


def _mounts_node():
    builder = _MountsBuilder()
    return builder.new_root().mounts()


def test_closed_signature_rejects_undeclared_attribute():
    """No **kwargs means the declared names are the whole accepted set."""
    node = _mounts_node()
    with pytest.raises(ValueError, match="bogus"):
        node.annotated(name="x", bucket="b", bogus=1)


def test_closed_signature_rejects_undeclared_without_type_hints():
    """Closedness must not depend on annotations: same rejection, no hints."""
    node = _mounts_node()
    with pytest.raises(ValueError, match="bogus"):
        node.plain(name="x", bucket="b", bogus=1)


def test_unannotated_declared_attribute_is_not_type_checked():
    """An unannotated parameter accepts any value: it declares a name only."""
    node = _mounts_node()
    node.plain(name=42, bucket="b")  # no hint, so no type to violate


def test_error_names_the_element_and_the_declared_set():
    """The message must say what was passed and what the element accepts."""
    node = _mounts_node()
    with pytest.raises(ValueError) as excinfo:
        node.annotated(name="x", bucket="b", endpoint_ur="typo")
    message = str(excinfo.value)
    assert "annotated" in message
    assert "endpoint_ur" in message
    assert "bucket" in message and "name" in message


def test_var_keyword_signature_stays_open():
    """An explicit **kwargs is the author declaring an open attribute set."""
    node = _mounts_node()
    node.opened(name="x", anything=1, data_foo="y")


def test_framework_kwargs_pass_a_closed_signature():
    """nodeId and friends are consumed by the framework, never declared."""
    node = _mounts_node()
    node.annotated(name="x", bucket="b", nodeId="m1")


def test_old_source_identity_spelling_is_not_a_framework_keyword():
    node = _mounts_node()
    with pytest.raises(ValueError, match="node_id"):
        node.annotated(name="x", bucket="b", node_id="m1")


def test_id_is_not_a_framework_kwarg():
    """``id`` is a dialect's word, not the core's.

    HTML has an ``id`` attribute; a configuration or SQL grammar does not.
    Exempting it framework-wide would let every grammar silently accept a
    name that means nothing to it — so a closed signature rejects it like
    any other undeclared attribute, and an element that wants it declares
    it.
    """
    node = _mounts_node()
    with pytest.raises(ValueError, match="does not accept 'id'"):
        node.annotated(name="x", bucket="b", id="whatever")


def test_markup_element_keeps_arbitrary_attributes():
    """The dialects declare **kwargs, so HTML attributes still flow."""
    from genro_builders.contrib.html import HtmlBuilder

    builder = HtmlBuilder()
    div = builder.source.div()
    div.span("hi", class_="x", data_foo=1, aria_label="y")
    out = builder.render()
    assert 'data_foo="1"' in out or 'data-foo="1"' in out
    assert "hi" in out


def test_positional_value_still_reaches_the_node():
    """div('alfa') keeps meaning 'the value of the div'."""
    from genro_builders.contrib.html import HtmlBuilder

    builder = HtmlBuilder()
    builder.source.div("alfa")
    assert "alfa" in builder.render()
