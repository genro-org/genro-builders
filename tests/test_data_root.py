# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Tests for the stable root of the datastore (issue #37).

The datastore has the same shape as the source: a private wrapper
``_dataroot`` holding one content node ``DATA_ROOT`` (``_root_``), backrefs
on. ``builder.data`` / ``node.data`` is the content Bag, so author paths
do not carry the structural segment. A subscriber on the wrapper sees
every change under the content, with ``_root_`` as the first element of
the pathlist. Sub-builders share both the content Bag and the wrapper.
"""
from __future__ import annotations

from genro_bag import Bag

from genro_builders.builder.base import DATA_ROOT, SOURCE_ROOT
from genro_builders.contrib.html import HtmlBuilder


def _recording(wrapper: Bag) -> list[tuple[str, list[str]]]:
    """Subscribe on ``wrapper``; return the list the events land in."""
    events: list[tuple[str, list[str]]] = []

    def record(**kw) -> None:
        events.append((kw["evt"], list(kw["pathlist"])))

    wrapper.subscribe("probe", any=record)
    return events


class Page(HtmlBuilder):
    def setup(self, data) -> None:
        data.set_item("fill", "red")
        data.set_item("title", "hello")

    def main(self, root) -> None:
        body = root.body()
        body.div("^title", nodeId="title")
        body.svg(width=10).rect(nodeId="shape", fill="^fill")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_data_root_has_the_source_root_value():
    assert DATA_ROOT == "_root_"
    assert DATA_ROOT == SOURCE_ROOT


def test_data_is_the_content_node_of_the_wrapper():
    builder = HtmlBuilder()
    assert isinstance(builder._dataroot, Bag)
    assert builder._dataroot.keys() == [DATA_ROOT]
    assert builder._dataroot[DATA_ROOT] is builder.data


def test_data_parent_chain_reaches_the_wrapper():
    builder = HtmlBuilder()
    assert builder._dataroot.backref is True
    assert builder.data.backref is True
    assert builder.data.parent is builder._dataroot
    assert builder.data.parent_node.label == DATA_ROOT
    builder.data.set_item("a.b", 1)
    assert builder.data.get_item("a").root is builder._dataroot


def test_node_data_is_the_content_bag():
    page = Page()
    page.create()
    assert page.node_by_id("title").data is page.data
    assert page.node_by_id("shape").data is page.data


# ---------------------------------------------------------------------------
# Subscriber on the wrapper
# ---------------------------------------------------------------------------


def test_wrapper_subscriber_receives_nested_insert():
    builder = HtmlBuilder()
    events = _recording(builder._dataroot)
    builder.data.set_item("a.b", 1)
    assert events == [
        ("ins", ["_root_"]),
        ("ins", ["_root_", "a"]),
    ]


def test_wrapper_subscriber_receives_nested_update():
    builder = HtmlBuilder()
    builder.data.set_item("a.b", 1)
    events = _recording(builder._dataroot)
    builder.data.set_item("a.b", 2)
    assert events == [("upd_value", ["_root_", "a", "b"])]


def test_wrapper_subscriber_receives_nested_delete():
    builder = HtmlBuilder()
    builder.data.set_item("a.b", 1)
    events = _recording(builder._dataroot)
    builder.data.del_item("a.b")
    assert events == [("del", ["_root_", "a"])]


def test_wrapper_subscriber_receives_node_relative_writes():
    page = Page()
    page.create()
    events = _recording(page._dataroot)
    page.node_by_id("title").set_relative_data("title", "bye")
    assert events == [("upd_value", ["_root_", "title"])]


# ---------------------------------------------------------------------------
# Author paths and sub-builders
# ---------------------------------------------------------------------------


def test_author_paths_do_not_carry_the_structural_segment():
    page = Page()
    page.create()
    assert page.data.get_item("title") == "hello"
    assert page._dataroot.get_item(f"{DATA_ROOT}.title") == "hello"
    assert page.node_by_id("title").abs_datapath("^title") == "title"
    out = page.render(target=False)
    assert "<div>hello</div>" in out
    assert '<rect fill="red" />' in out


def test_subbuilder_shares_content_and_wrapper():
    page = Page()
    page.create()
    svg = page.get_subbuilder("svg")
    assert svg.data is page.data
    assert svg._dataroot is page._dataroot


def test_wrapper_subscriber_receives_subbuilder_writes():
    page = Page()
    page.create()
    shape = page.node_by_id("shape")
    assert type(shape._resolve_builder()).__name__ == "SvgBuilder"
    events = _recording(page._dataroot)
    shape.set_relative_data("fill", "blue")
    assert events == [("upd_value", ["_root_", "fill"])]
    assert '<rect fill="blue" />' in page.render(target=False)
