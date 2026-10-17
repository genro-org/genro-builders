# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""06 — Data presentation: the datum knows how to present itself. See readme.md."""
from __future__ import annotations

from genro_builders.contrib.html import HtmlBuilder


class CustomPage(HtmlBuilder):
    def setup(self, data):
        # mask: how the value is written wherever it is rendered
        # (legacy gnrformatter vocabulary: %s is the value).
        data.set_item("temperature", 39.2, mask="%s°", _wdg={"color": "red"})
        # _wdg: exception attributes that travel WITH the datum and win
        # over the recipe's static defaults (an alarm color).
        data.set_item("box_width", 120)

    def main(self, root):
        body = root.body()
        # The recipe says gray; the datum carries the exception: red wins.
        body.div("^temperature", color="gray")
        # The explicit suffix appends a unit to the typed Data value.
        body.div("sized box", width="^box_width:{}px", border="1px solid")


if __name__ == "__main__":
    page = CustomPage()
    page.create()
    page.set_render_target("output.html")
    page.render(pretty=True)
    print(page.rendered_target)
