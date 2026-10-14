# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Contract: ``include_components`` enriches ONE instance's grammar.

The mixin's ``@component`` methods become available on that builder
instance only: the class schema is copied on first use, so other
instances of the same builder keep the grammar they were born with.
"""
from __future__ import annotations

import pytest

from genro_builders.builder import component
from genro_builders.contrib.html import HtmlBuilder


class Extra:
    @component
    def badge(self, root):
        root.span("new", class_="badge")


class Page(HtmlBuilder):
    def main(self, root):
        root.body().badge()


def test_included_component_enters_the_grammar_of_the_instance():
    page = Page()
    page.include_components(Extra)
    page.create()
    body = next(iter(page.source)).value
    assert [node.node_tag for node in body] == ["badge"]


def test_another_instance_keeps_the_class_grammar():
    enriched = Page()
    enriched.include_components(Extra)
    plain = Page()
    with pytest.raises(AttributeError, match="badge"):
        plain.create()
