# genro-builders

Builder system for [genro-bag](https://github.com/genropy/genro-bag) —
domain-specific grammars, rendering, and runtime data binding via
pointers, built on top of bag data structures.

## Installation

```bash
pip install genro-builders
```

## Quick start

A page is a builder: subclass the dialect and implement `main`.

```python
from genro_builders.contrib.html import HtmlBuilder


class HelloPage(HtmlBuilder):
    def main(self, root):
        body = root.body()
        body.h1("Hello World")
        body.p("My first page with genro-builders.")


page = HelloPage()
page.create()
print(page.render(pretty=True))
```

The lifecycle is two-phase, both on the builder:

- **`create()`** runs `setup(self.data)` (seed the data), then the
  user-defined `main(self.source)` that populates the source Bag
  through the dialect's grammar API, then the first calculation of
  the data-elements.
- **`render(mode=None, target=None, **opts)`** drives the universal walk
  on the source and produces the dialect's output. Default `mode` comes
  from the dialect; default `target` returns the string. It composes two
  steps you can also call on their own: `materialize(mode)` walks and
  keeps the result in `materialized[mode]`, `finalize` delivers it.

Rendering does not validate. `validate_source()` reports the nodes whose
minimum child cardinality is unmet — `(fullpath, [missing tags])` per
node, empty when complete — when the author asks for it.

## Dialects (contrib)

The package ships with reference dialects, each as a `<Dialect>Builder`
grammar:

- **HTML5** — `genro_builders.contrib.html.HtmlBuilder`
  (HTML5 grammar with CSS kwargs)
- **SVG** — `genro_builders.contrib.svg.SvgBuilder`
- **CSS** — `genro_builders.contrib.css.CssBuilder`
- **XSD** — `genro_builders.xml` (codegen: an XSD schema becomes a
  `<Dialect>Builder` you commit and import)

Mixed-dialect documents are supported via sub-builders: a grammar
element marked `_meta['subbuilder']` switches the active dialect from
that node down, and the render walk picks the right renderer per node.
HTML hosts SVG with `body.svg(...)`; SVG hosts HTML with
`svg.html(...)`, wrapped in `<foreignObject>` automatically.

```python
from genro_builders.contrib.html import HtmlBuilder


class Badge(HtmlBuilder):
    def main(self, root):
        body = root.body()
        svg = body.svg(viewBox="0 0 200 80", width=200, height=80)
        svg.rect(x=0, y=0, width=200, height=80, fill="#2c3e50")


page = Badge()
page.create()
print(page.render())
```

## Architecture (one-paragraph map)

A **builder** declares the grammar of a dialect (decorators
`@element`, `@abstract`; the three data-elements `dataSetter` /
`dataFormula` / `dataController` are plain `@element` marked as
data) and is also the document: it owns `name`, `source`,
`create()`/`render()`, and exposes its renderers as `renderer_<mode>`
properties. It also owns its **datastore**: one FLAT Bag, `builder.data`,
with absolute paths and no leading segment — reachable from any node as
`node.data`. As the source, it is the content node `_root_` of a private
wrapper, `_dataroot`, so the datastore is a tree. A
**renderer** is responsible for one mode: the universal walk produces
fragments via dialect-specific `rendered_item`, then `finalize` ships
the result to the target.

The builder also declares the class of its Source: `_source_class`
(default `SourceBag`), redefinable per subclass. The Source declares
the class of its nodes (`_node_class`). Branches follow the class of
their parent bag. See [the Source class](docs/builders/overview.md#the-source-class).

## Runtime data binding (pull-based)

Attribute values and node text can carry pointers and templates,
resolved at render time:

- `^path` — pointer declared as meant to follow the datum
- `=path` — passive pointer (read only)

Both resolve the same way in a static render: the difference is the
author's declaration of intent, which a reactive engine would act on.
- `${name}` — template token, expanded only inside attributes (never in the
  node value nor in data-element attributes; `\${name}` stays literal); an
  attribute referenced by a template of the same node is a consumed input,
  never emitted

```python
from genro_builders.contrib.html import HtmlBuilder


class Page(HtmlBuilder):
    def setup(self, data):
        data.set_item("greeting", "Hello")

    def main(self, root):
        root.body().h1("^greeting")


page = Page()
page.create()                  # setup + main + the data-elements
print(page.render())
# ...<h1>Hello</h1>...

# Mutate the data and re-render: pull-based, no auto-render.
page.data.set_item("greeting", "Ciao")
print(page.render())
# ...<h1>Ciao</h1>...
```

Re-render is the whole reactivity model here: change the data, render
again. Fine-grained reactivity is a separate engine, still under design —
see the `RX` area of the contract.

The companion API on each source node:

- `node.abs_datapath(path)` — turn a relative path into an absolute
  one in the datastore
- `node.get_relative_data(path)` / `node.set_relative_data(path,
  value)` — read/write the datastore relative to the node
- `node.SET / GET / PUT / FIRE` — DSL macros over the same two entry
  points; the `fired`/`reason` flags they carry travel through the
  genro-bag subscribe pipeline, and nothing in this package acts on
  them (vocabulary for the future reactive engine)

## Render target

```python
page = HelloPage()
page.create()

# Return a string (default)
text = page.render()

# Write to a path
page.render(target="out.html")

# Push to a file-like or invoke a callable
import io
page.render(target=io.StringIO())
page.render(target=print)

# Register a default target (per mode), then render to it
page.set_render_target("out.html")
page.render()
```

## Examples

Runnable tutorials under
[`src/genro_builders/contrib/<dialect>/examples/`](src/genro_builders/contrib/),
grouped by scenario:

- HTML — `no_data/` (grammar, styling, sub-builders, validation,
  render modes), `with_data/` (pointers, datapath, presentation),
  `with_logic/` (data-elements)
- SVG — `01_introduction`, `badge_sheet`, `bar_chart`, and more
- CSS — `01_introduction`
- XSD — `01_person_schema`; XSLT — `01_sitemap_to_html`

Each example ships a runnable `.py`, a `readme.md`, and the rendered
output. The test suite runs them all (`tests/test_examples.py`).

## Documentation

- [Getting Started](docs/getting-started.md) — first page in 5 minutes
- [Builders overview](docs/builders/overview.md) — builder/renderer split
- [Decorators](docs/builders/decorators.md) — `@element`, `@abstract`, sub-builders, data-elements
- [Common patterns](docs/builders/patterns.md) — `._` chaining, `node_by_id`, render targets
- Per-grammar references: [HTML](docs/grammars/html.md), [SVG](docs/grammars/svg.md), [CSS](docs/grammars/css.md), [XSD](docs/grammars/xsd.md)
- Architectural contract and roadmap: [`roadmap/`](roadmap/)

## Downstream

genro-builders is a generic engine: the grammars, the renderers, and the
pull-based data binding know nothing about who consumes them. The source carries
no reference to any downstream layer — this is the one place that names them.
Known consumers in the Genro ecosystem:

- **[genro-ws-web](https://github.com/genropy/genro-ws-web)** — WebSocket-driven
  reactive SPA framework (the production widget kit and the push transport live
  here)
- **[genro-office](https://github.com/genropy/genro-office)** — Office document
  generation (Word and Excel builders)
- **[genro-print](https://github.com/genropy/genro-print)** — print and PDF
  generation system
- **[genro-textual](https://github.com/genropy/genro-textual)** — Textual UI
  framework for Bag-driven applications
- **[genro-scriba](https://github.com/genropy/genro-scriba)** — infrastructure
  configuration file generator (Traefik, Docker Compose, and more)

## License

Apache License 2.0 — Copyright 2025 Softwell S.r.l.

Reusable named input constraints: see [CustomTypes](docs/builders/custom-types.md) for
`ct.register(name, type, annotation)`, `ct.name` signatures, and Python/JS catalogs.
