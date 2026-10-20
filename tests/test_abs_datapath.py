# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Tests for SourceBagNode.abs_datapath.

Composes the absolute datastore path for a node's pointer/path. The store
is flat — one builder, one Bag (``builder.data``) — so an absolute path
carries no leading segment: ``field`` composes to ``field``, not
``<mount>.field``.

Covers all supported path forms:

    ``field``           — already absolute, returned as is
    ``^field``          — strip pointer mark
    ``field?attr``      — preserve ?attr tail
    ``.x``              — relative: walk ancestor datapath chain
    ``a.#parent.b``     — #parent collapses preceding segment
    ``#FORM.x``         — nearest ancestor with formId or form=True
    ``#ANCHOR.x``       — nearest ancestor with attr _anchor present
    ``#<nodeId>.x``    — node carrying that nodeId

Test pattern: a Page(HtmlBuilder) runs ``page.create()``; assert on the
string returned by abs_datapath, never on private helpers.
"""
from __future__ import annotations

from typing import Callable

import pytest

from genro_builders.contrib.html import HtmlBuilder


def _leaf(main_fn: Callable, node_id: str = "leaf"):
    """Mount a page whose ``main`` runs ``main_fn(root)``; return its node."""

    class Page(HtmlBuilder):
        def main(self, root) -> None:
            main_fn(root)

    page = Page(name="main")
    page.create()
    return page, page.node_by_id(node_id)


def _simple():
    """A bare leaf node: no datapath ancestors to walk."""
    return _leaf(lambda root: root.body(nodeId="leaf"))


# ---------------------------------------------------------------------------
# Absolute paths
# ---------------------------------------------------------------------------


def test_absolute_field_is_returned_as_is():
    _page, leaf = _simple()
    assert leaf.abs_datapath("field") == "field"


def test_absolute_dotted_path_is_returned_as_is():
    _page, leaf = _simple()
    assert leaf.abs_datapath("user.name") == "user.name"


# ---------------------------------------------------------------------------
# Pointer mark (^) stripping
# ---------------------------------------------------------------------------


def test_pointer_mark_is_stripped():
    _page, leaf = _simple()
    assert leaf.abs_datapath("^field") == "field"


def test_pointer_mark_stripped_on_dotted_path():
    _page, leaf = _simple()
    assert leaf.abs_datapath("^user.name") == "user.name"


# ---------------------------------------------------------------------------
# Eager pointer mark (=) stripping — symmetric to ^ (DB-D9)
# ---------------------------------------------------------------------------


def test_equals_mark_is_stripped():
    _page, leaf = _simple()
    assert leaf.abs_datapath("=field") == "field"


def test_equals_mark_stripped_on_dotted_path():
    _page, leaf = _simple()
    assert leaf.abs_datapath("=user.name") == "user.name"


def test_equals_mark_with_attr_tail():
    _page, leaf = _simple()
    assert leaf.abs_datapath("=field?color") == "field?color"


# ---------------------------------------------------------------------------
# ?attr tail preserved
# ---------------------------------------------------------------------------


def test_attr_tail_preserved():
    _page, leaf = _simple()
    assert leaf.abs_datapath("field?color") == "field?color"


def test_attr_tail_preserved_with_pointer_mark():
    _page, leaf = _simple()
    assert leaf.abs_datapath("^field?color") == "field?color"


# ---------------------------------------------------------------------------
# Relative paths — ancestor walk (P2)
# ---------------------------------------------------------------------------


def _with_datapath():
    """body has datapath='myform'; the leaf is a child of body."""
    return _leaf(lambda root: root.body(datapath="myform").div(nodeId="leaf"))


def test_relative_resolves_via_ancestor_datapath():
    _page, leaf = _with_datapath()
    assert leaf.abs_datapath(".name") == "myform.name"


def test_relative_with_attr_tail_preserved():
    _page, leaf = _with_datapath()
    assert leaf.abs_datapath(".name?color") == "myform.name?color"


def test_relative_with_pointer_mark():
    _page, leaf = _with_datapath()
    assert leaf.abs_datapath("^.name") == "myform.name"


def test_relative_with_equals_mark():
    _page, leaf = _with_datapath()
    assert leaf.abs_datapath("=.name") == "myform.name"


def test_relative_chains_through_relative_ancestor_datapath():
    """Chain of datapaths: grandparent absolute, parent relative."""

    def build(root) -> None:
        outer = root.body(datapath="form")
        inner = outer.div(datapath=".row")
        inner.span(nodeId="leaf")

    _page, leaf = _leaf(build)
    assert leaf.abs_datapath(".name") == "form.row.name"


def test_relative_without_anchor_raises_value_error():
    _page, leaf = _leaf(lambda root: root.body().div(nodeId="leaf"))
    with pytest.raises(ValueError):
        leaf.abs_datapath(".name")


def test_relative_walk_uses_leaf_datapath_too():
    """If the leaf itself carries an absolute datapath, the walk starts
    from the node (current = node)."""
    _page, leaf = _leaf(
        lambda root: root.body().div(nodeId="leaf", datapath="own")
    )
    assert leaf.abs_datapath(".name") == "own.name"


# ---------------------------------------------------------------------------
# #parent path-level rewrite (filesystem ".." equivalent)
# ---------------------------------------------------------------------------


def test_parent_collapses_preceding_segment():
    _page, leaf = _simple()
    assert leaf.abs_datapath("a.b.#parent.c") == "a.c"


def test_parent_collapses_multiple_segments():
    _page, leaf = _simple()
    assert leaf.abs_datapath("a.b.c.#parent.#parent.d") == "a.d"


def test_parent_after_relative_resolution():
    """#parent applies AFTER the ancestor walk has composed the path."""
    _page, leaf = _with_datapath()       # body.datapath="myform"
    # relative resolves to "myform.row.name", then #parent collapses "row"
    assert leaf.abs_datapath(".row.#parent.name") == "myform.name"


def test_parent_with_nothing_to_cancel_raises():
    """No silent drop: too many #parent segments raises ValueError."""
    _page, leaf = _simple()
    with pytest.raises(ValueError):
        leaf.abs_datapath("a.#parent.#parent.b")


# ---------------------------------------------------------------------------
# Symbolic scopes (P3): #FORM, #ANCHOR, #nodeId
# ---------------------------------------------------------------------------


def test_symbolic_form_with_formId():
    """#FORM resolves to the nearest ancestor with attr formId set."""
    _page, leaf = _leaf(
        lambda root: root.body(formId="inv", datapath="f").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("#FORM.x") == "f.x"


def test_symbolic_form_with_form_true():
    """#FORM also matches form=True (DB-D3, replaces legacy _fakeform)."""
    _page, leaf = _leaf(
        lambda root: root.body(form=True, datapath="f").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("#FORM.x") == "f.x"


def test_symbolic_form_walks_past_unmarked_intermediate():
    """The walk continues past ancestors that are not marked."""

    def build(root) -> None:
        outer = root.body(formId="inv", datapath="f")
        inner = outer.div()                  # unmarked intermediate
        inner.span(nodeId="leaf")

    _page, leaf = _leaf(build)
    assert leaf.abs_datapath("#FORM.x") == "f.x"


def test_symbolic_form_without_marked_ancestor_raises_key_error():
    _page, leaf = _leaf(lambda root: root.body().div(nodeId="leaf"))
    with pytest.raises(KeyError):
        leaf.abs_datapath("#FORM.x")


def test_symbolic_anchor_with_attribute_presence():
    """#ANCHOR matches the nearest ancestor with attr _anchor present."""
    _page, leaf = _leaf(
        lambda root: root.body(_anchor="whatever", datapath="a").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("#ANCHOR.x") == "a.x"


def test_symbolic_anchor_value_is_arbitrary():
    """_anchor value is arbitrary: presence alone is the marker."""
    _page, leaf = _leaf(
        lambda root: root.body(_anchor=True, datapath="a").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("#ANCHOR.x") == "a.x"


def test_symbolic_anchor_without_marker_raises_key_error():
    _page, leaf = _leaf(lambda root: root.body().div(nodeId="leaf"))
    with pytest.raises(KeyError):
        leaf.abs_datapath("#ANCHOR.x")


def test_symbolic_node_id_resolves_via_node_by_id():
    """#<id> dispatches to node_by_id and composes with the target's datapath."""
    _page, leaf = _leaf(
        lambda root: root.body(nodeId="hub", datapath="rec").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("#hub.x") == "rec.x"


def test_symbolic_unknown_id_raises_key_error():
    _page, leaf = _simple()
    with pytest.raises(KeyError):
        leaf.abs_datapath("#totally-unknown.x")


def test_symbolic_with_pointer_mark():
    """^#FORM.x: pointer mark is stripped, symbolic dispatch happens after."""
    _page, leaf = _leaf(
        lambda root: root.body(formId="inv", datapath="f").div(nodeId="leaf")
    )
    assert leaf.abs_datapath("^#FORM.x") == "f.x"
