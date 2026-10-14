# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Contract: a Source travels on the TYTX wire as "::X" with __cls "SourceBag".

SourceBag has no TYTX suffix of its own: it is registered in the genro-tytx
subtype dictionary of "X" under its class name, and genro-bag writes the name
wherever the class differs from the inherited one. Decoding rebuilds the
SourceBag branches detached (no builder), with SourceBagNode nodes.
"""
from __future__ import annotations

import pytest
from genro_bag import Bag
from genro_tytx import from_tytx, get_subtype_dict, to_tytx

from genro_builders import SourceBag, SourceBagNode
from genro_builders.contrib.html import HtmlBuilder


class Page(HtmlBuilder):
    def main(self, root):
        body = root.body()
        body.div("hello", id="greeting")
        body.div().span("inner")


@pytest.fixture
def source():
    page = Page()
    page.create()
    return page.source


def test_registered_under_its_name():
    assert get_subtype_dict("X")["SourceBag"] is SourceBag


def test_root_carries_the_class_name(source):
    assert from_tytx(source.to_tytx().removesuffix("::X"))["__cls"] == "SourceBag"


@pytest.mark.parametrize("caller", [Bag, SourceBag])
def test_source_roundtrip(source, caller):
    result = caller.from_tytx(source.to_tytx())
    assert type(result) is SourceBag
    assert all(type(node) is SourceBagNode for node in result)
    branches = [node.value for node in result.get_nodes() if isinstance(node.value, Bag)]
    assert branches and all(type(branch) is SourceBag for branch in branches)
    assert result.to_tytx() == source.to_tytx()


def test_generic_tytx_encoder(source):
    """The host sends builder.source through genro_tytx.to_tytx."""
    decoded = from_tytx(to_tytx(source))
    assert type(decoded) is SourceBag
    assert decoded.to_tytx() == source.to_tytx()


def test_data_bag_inside_source_stays_a_bag(source):
    source.set_item("payload", Bag({"value": 1}))
    wire = from_tytx(source.to_tytx().removesuffix("::X"))
    rows = {row[1]: row[4] for row in wire["rows"]}
    assert rows["payload"]["__cls"] == "Bag"
    assert type(SourceBag.from_tytx(source.to_tytx())["payload"]) is Bag
