# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Contract: a builder declares the SourceBag class of its Source.

``BuilderBase._source_class`` names the class instantiated for
``_sourceroot``, for the ``source`` payload, for ``new_root`` and for the
component expansion root (legacy GenroPy ``domSrcFactory``). The Source
declares the class of its nodes (``_node_class``). Branches created while
authoring, including the promotion of a scalar node, follow the class of
their parent bag. On the TYTX wire the class survives when it is
registered in the subtype dictionary of ``X``.
"""
from __future__ import annotations

from genro_bag import Bag
from genro_tytx import from_tytx, get_subtype_dict, set_subtype_dict, to_tytx

from genro_builders import SourceBag, SourceBagNode
from genro_builders.builder import BuilderBase, element


class _TestSourceNode(SourceBagNode):
    __slots__ = ()


class _TestSource(SourceBag):
    _node_class = _TestSourceNode


set_subtype_dict(
    _TestSource.__tytx_suffix__,
    {**get_subtype_dict(_TestSource.__tytx_suffix__), "_TestSource": _TestSource},
)


class _BoxBuilder(BuilderBase):
    @element(sub_tags="*")
    def box(self, **kwargs): ...

    @element(sub_tags="")
    def leaf(self, **kwargs): ...


class _TestSourceBuilder(_BoxBuilder):
    _source_class = _TestSource

    def main(self, root):
        outer = root.box()
        outer.box().leaf("hello")
        promoted = root.box("scalar")
        promoted.leaf("child")


def _branches(bag):
    """Every Bag value of the tree, depth first."""
    for node in bag:
        if isinstance(node.value, Bag):
            yield node.value
            yield from _branches(node.value)


def _nodes(bag):
    """Every node of the tree, depth first."""
    for node in bag:
        yield node
        if isinstance(node.value, Bag):
            yield from _nodes(node.value)


def _page():
    page = _TestSourceBuilder()
    page.create()
    return page


def test_default_source_class_is_sourcebag():
    page = _BoxBuilder()
    assert BuilderBase._source_class is SourceBag
    assert type(page._sourceroot) is SourceBag
    assert type(page.source) is SourceBag


def test_root_and_wrapper_use_the_declared_class():
    page = _page()
    assert type(page._sourceroot) is _TestSource
    assert type(page.source) is _TestSource
    assert page.source._builder is page


def test_nested_branches_and_nodes_follow_the_parent_class():
    page = _page()
    branches = list(_branches(page.source))
    assert len(branches) == 3
    assert all(type(branch) is _TestSource for branch in branches)
    assert all(type(node) is _TestSourceNode for node in _nodes(page.source))


def test_promoted_scalar_node_gets_the_declared_class():
    page = _page()
    promoted = page.source.get_node("box_1")
    assert type(promoted.value) is _TestSource
    assert type(promoted.value.get_node("leaf_0")) is _TestSourceNode


def test_new_root_and_expansion_root_use_the_declared_class():
    page = _TestSourceBuilder()
    assert type(page.new_root()) is _TestSource
    expansion = page._expansion_root()
    assert type(expansion) is _TestSource
    assert type(expansion.parent_node.parent_bag) is _TestSource


def test_registered_subclass_survives_the_tytx_wire():
    source = _page().source
    payload = source.to_tytx()
    wire = from_tytx(payload.removesuffix("::X"))
    assert wire["__cls"] == "_TestSource"
    assert all("__cls" not in row[4] for row in wire["rows"])
    typed = to_tytx(source)
    assert typed.endswith("::X")
    for result in (from_tytx(typed), SourceBag.from_tytx(payload)):
        assert type(result) is _TestSource
        assert all(type(branch) is _TestSource for branch in _branches(result))
        assert all(type(node) is _TestSourceNode for node in _nodes(result))
        assert result.to_tytx() == payload
