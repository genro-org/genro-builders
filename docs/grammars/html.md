# HTML grammar

**Last Updated**: 2026-07-27
**Status**: 🟢 APPROVATO — allineato al contratto v0.9.0 (renderer-side chain landed 2026-05-30).
**Maintainer**: core team.

HTML5 grammar originally derived from the W3C schema. 113 elements,
full parent/child validation.

## Purpose

Produce HTML5 markup. Supports both XHTML-style self-closing void
tags (`<img/>`) and bare HTML5 (`<img>`), with optional pretty
printing. Pairs with `HtmlRenderer` for serialization. Pairs with
the CSS-kwarg machinery for inline styling.

## Quick start

```python
from genro_builders.contrib.html import HtmlBuilder


class Page(HtmlBuilder):
    def main(self, root):
        root.html().head().title("Hello")
        body = root.html().body()
        body.h1("Hello")
        body.p("genro-builders")


p = Page(); p.create()
print(p.render(pretty=True))
```

## Elements

The grammar was originally derived from the W3C HTML5 Validator schema
([html5_elements.py](../../src/genro_builders/contrib/html/html5_elements.py)).
It contains 113 tags grouped by content category (flow content,
phrasing content, etc.) plus their parent and sub-tag constraints.

> **Note**: the file is no longer fully auto-generated. It was seeded
> from the W3C schema but is now **hand-maintained**: edits and
> additions go in directly. The schema-diff utility in
> `importer/html5_schema_builder.py` exists to spot W3C drift on
> demand, not to regenerate the file.

Highlights:

- All 16 HTML5 **void elements** are present as leaves:
  `area`, `base`, `br`, `col`, `embed`, `hr`, `img`, `input`,
  `link`, `meta`, `param`, `source`, `track`, `wbr`, `command`,
  `keygen`.
- Container elements use the W3C content categories.
- A subset of phrasing elements is exposed under abstracts like
  `phrasing`, `flow`, `interactive` (no `@` prefix; abstracts live
  in the dedicated `_abstracts` sub-bag of the class schema).

Refer to the auto-generated module for the exhaustive list.

## Common patterns

### Attributes with reserved Python keywords

Some HTML attribute names collide with Python keywords (`class`,
`for`). The grammar uses an underscore prefix to disambiguate:

```python
body.div(class_="card")
body.label(_for="email")
```

The renderer strips the leading underscore on output.

### Inline CSS via kwargs

`HtmlRenderer` recognizes 24 CSS root names as kwargs and emits
them in a `style="..."` attribute. Sub-properties use underscore
syntax:

```python
body.div(
    "content",
    id="main", class_="card",
    color="red",
    background="#fff",
    padding="12px",
    padding_top=10,
    font_size="14px",
    text_align="center",
    rounded=12,
    transform_rotate=-3,
    style="margin: 4px",
)
```

`style_<prop>` is the escape hatch for CSS properties outside the
curated 24:

```python
body.div(style_aspect_ratio="16 / 9")
```

For the full kwarg / macro reference see
[../builders/patterns.md](../builders/patterns.md) and the
renderer source.

### Chaining leaves with `._`

```python
body.h1("Title")\
   ._.p("paragraph one")\
   ._.p("paragraph two")
```

See [../builders/patterns.md](../builders/patterns.md).

## Render

`HtmlRenderer` produces HTML5 markup through the universal walk:
`RendererBase.render(source, **opts)` recurses on the source bag,
and `HtmlRenderer.rendered_item(node, item, runtime_attrs, **opts)`
emits the fragment for each node.

Mode-specific kwargs available at `page.render(...)`:

| Kwarg | Default | Effect |
|-------|---------|--------|
| `xml` | `True` | Void tags as `<img/>` (XHTML). `False` → `<img>` (HTML5). |
| `pretty` | `False` | Two-space indentation and trailing newline per node. |

The `xml` mode is inherited from `BuilderBase.renderer_xml`. It is a
real render — it rides the universal walk, so pointers are resolved and
framework markers (`nodeId`, …) are filtered out, exactly like the
`html` render. For the raw structural view of the source (markers and
unresolved pointers shown verbatim) call `page.source.to_xml()` on
the bag directly: that is a different thing from `render(mode="xml")`.

## Validation rules

- `<rect>`, `<circle>`, `<path>` and other SVG tags are **not**
  valid here. The grammar rejects them unless they appear inside the
  `<svg>` sub-builder boundary
  (`@element(_meta={"subbuilder": "svg"})`).
- `<li>` must appear inside `<ul>` or `<ol>`.
- `<head>` elements (title, meta, link, ...) reject body content.
- Void tags reject children.

Validation errors raise `ValueError` at `create()` time.

## Worked examples

Three ready-to-run examples live under
[src/genro_builders/contrib/html/examples/](https://github.com/genropy/genro-builders/tree/main/src/genro_builders/contrib/html/examples/),
each in the three-view format (`.py`, `.ipynb`, rendered `.html`):

- `00_hello_world/` and following — see `examples/no_data/`.
- `02_inline_styling/` — CSS kwarg machinery, macros, escape
  syntax.
- `03_subbuilders/` — HTML hosting SVG and SVG hosting HTML via
  `<foreignObject>`.

## Known limitations

- The grammar covers HTML5 but not yet HTML5 templates,
  custom-element semantics, or shadow DOM.
- No automatic doctype prepend. The user adds `<!DOCTYPE html>` by
  hand when needed.
- HTML5-specific accessibility hints (`aria-*` attributes) are
  not validated — they pass through as opaque kwargs.

## References

- Source: `src/genro_builders/contrib/html/`.
- Renderer: `src/genro_builders/contrib/html/html_renderer.py`.
- Schema (generated): `src/genro_builders/contrib/html/html5_elements.py`.
- Contract: `roadmap/architecture-contract.md`.
