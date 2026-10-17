# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Explicit suffix templates preserve Source and independently projected attributes."""
from __future__ import annotations

from genro_builders.contrib.html import HtmlBuilder


def _render(main_fn):
    class Page(HtmlBuilder):
        def main(self, root) -> None:
            main_fn(root)

    page = Page(name="main")
    page.create()
    return page.render(target=False)


def test_explicit_template_formats_the_leading_pointer():
    def main(root):
        body = root.body()
        body.dataSetter("mywidth", 120)
        body.div("testo", width="^mywidth:{}px")

    out = _render(main)
    assert '<div style="width: 120px">testo</div>' in out
    assert "w=" not in out


def test_old_templates_are_literal_and_keep_attributes():
    def main(root):
        root.div("x", t="hello", title="${t}", aria_label="${t} world")

    out = _render(main)
    assert 'title="${t}"' in out
    assert 'aria-label="${t} world"' in out or 'aria_label="${t} world"' in out
    assert ' t="hello"' in out


def test_value_is_literal_and_does_not_consume_attributes():
    def main(root):
        body = root.body()
        body.dataSetter("nome", "Mario")
        body.div("Ciao ${n}", n="^nome")

    out = _render(main)
    assert '<div n="Mario">Ciao ${n}</div>' in out
    assert 'n="Mario"' in out


def test_escaped_attribute_template_is_literal_and_does_not_consume():
    out = _render(lambda root: root.div(title=r"\${missing} ${name}", name="Mario"))
    assert r'title="\${missing} ${name}"' in out
    assert ' name="Mario"' in out


def test_raw_html_suffix_and_script_preserve_node_templates():
    def main(root):
        root.div("<b>${name}</b>::HTML")
        root.div("<b>${name}</b>")
        root.script('const text = `${name}`;')
    out = _render(main)
    assert "<div><b>${name}</b></div>" in out
    assert "<div>&lt;b&gt;${name}&lt;/b&gt;</div>" in out
    assert '<script>const text = `${name}`;</script>' in out
    assert "::HTML" not in out


def test_data_element_attributes_are_not_templates():
    class Page(HtmlBuilder):
        def main(self, root) -> None:
            body = root.body()
            body.dataSetter("total", 42)
            body.dataSetter("label", "${total}")
            body.dataFormula(
                destination="msg", func="echo",
                script="`Total: ${total}` ${stamp}", total="^total",
            )

        @staticmethod
        def echo(script, total):
            return f"{script}|{total}"

    page = Page(name="main")
    page.create()
    assert page.data.get_item("label") == "${total}"
    assert page.data.get_item("msg") == "`Total: ${total}` ${stamp}|42"


def test_old_template_with_missing_name_is_literal():
    assert 'title="${missing}"' in _render(lambda root: root.div(title="${missing}"))
