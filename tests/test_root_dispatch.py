# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Grammar semantics must be identical on both element-creation entry
points: a node (``body.div(...)``) and a bag (``root.div(...)``).

The runnable behaviours (sub-builder switch, data-element field mapping)
are covered by the examples ``no_data/08_root_dispatch`` and
``with_logic/03_root_logic`` through the examples runner. This module
covers the error contract, which an example cannot ship: ``nodeId``
uniqueness is enforced no matter which entry point creates the node.
"""
from __future__ import annotations

import pytest

from genro_builders.contrib.html import HtmlBuilder


def test_duplicate_node_id_on_root_raises():
    class Page(HtmlBuilder):
        def main(self, root):
            root.div(nodeId="dup")
            root.div(nodeId="dup")

    page = Page()
    with pytest.raises(ValueError, match="dup"):
        page.create()


def test_duplicate_node_id_on_node_raises():
    class Page(HtmlBuilder):
        def main(self, root):
            body = root.body()
            body.div(nodeId="dup")
            body.div(nodeId="dup")

    page = Page()
    with pytest.raises(ValueError, match="dup"):
        page.create()


def test_duplicate_node_id_across_entry_points_raises():
    class Page(HtmlBuilder):
        def main(self, root):
            body = root.body()
            body.div(nodeId="dup")     # node path
            root.div(nodeId="dup")     # bag path: same builder namespace

    page = Page()
    with pytest.raises(ValueError, match="dup"):
        page.create()


def test_duplicate_node_id_inside_subbuilder_subtree_raises():
    """Uniqueness is guaranteed by the ROOT builder: one nodeId
    namespace per document, sub-builder subtrees included."""
    class Page(HtmlBuilder):
        def main(self, root):
            svg = root.body().svg(viewBox="0 0 10 10")
            svg.rect(x=1, y=1, width=2, height=2, nodeId="dup")
            svg.rect(x=3, y=3, width=2, height=2, nodeId="dup")

    page = Page()
    with pytest.raises(ValueError, match="dup"):
        page.create()


def test_duplicate_node_id_across_dialect_boundary_raises():
    class Page(HtmlBuilder):
        def main(self, root):
            body = root.body()
            body.div(nodeId="dup")                       # host dialect
            svg = body.svg(viewBox="0 0 10 10")
            svg.rect(x=1, y=1, width=2, height=2, nodeId="dup")  # sub-dialect

    page = Page()
    with pytest.raises(ValueError, match="dup"):
        page.create()


def test_one_subbuilder_instance_per_host_dialect():
    """Sub-builder instances are cached on the host builder (the same
    pattern as the renderer cache): every svg subtree of the document
    shares one SvgBuilder, so the renderer cache keyed by id(builder)
    serves them all with a single sub-renderer."""
    captured = {}

    class Page(HtmlBuilder):
        def main(self, root):
            body = root.body()
            s1 = body.svg(viewBox="0 0 1 1")
            s2 = body.svg(viewBox="0 0 1 1")
            captured["same"] = s1._builder is s2._builder

    Page().create()
    assert captured["same"] is True
