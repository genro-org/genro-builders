# Builders overview

**Last Updated**: 2026-09-29
**Status**: 🟢 APPROVATO — allineato al contratto v0.9.0.

A builder is a Python class that defines a grammar for a structured
document — HTML, SVG, CSS, or any user-defined dialect — and IS the
document: it owns the source bag and the create/render lifecycle.

## The three objects

The framework is built around three concrete classes:

- **Builder** (`HtmlBuilder`, `SvgBuilder`, `CssBuilder`, ...) —
  declares the grammar via decorators AND carries the document: a
  `name` (a label, not an address), the `source` bag,
  `create()`/`render()`, the render targets. A page is a builder
  subclass with `main(self, root)`.
- **Renderer** (`HtmlRenderer`, `SvgRenderer`, `CssRenderer`, ...) —
  walks the source bag and emits a string. Exposed as
  `renderer_<mode>` properties on the builder class; instances are
  fresh and ephemeral (one `render()` call each).
The builder also owns the **datastore**: one FLAT Bag, `page.data`,
absolute paths with no leading segment. `setup(data)` seeds it, pointers
read it, and any node reaches it as `node.data` — same name at every
level. As the source, it is the content node `_root_` (`DATA_ROOT`) of
a private wrapper, `_dataroot`, with backrefs on. The segment is
structural, never part of an author path. A subscriber on the wrapper
receives every change under the content, with `_root_` as the first
element of the pathlist.

## The two phases

The builder's lifecycle has two phases, called explicitly:

```python
page = MyPage()
page.create()  # setup(data) + main(source) + first calculation
page.render()  # serializes source
```

| Phase | Method | What it does |
|-------|--------|--------------|
| Create | `page.create()` | Calls `setup(self.data)` (seed the data), then `self.main(self.source)` (user code populates the source bag), then the first calculation of the data-elements. |
| Render | `page.render(mode=None, target=None, **opts)` | Walks the source via `renderer_<mode>`. Returns the serialized output, or writes it to a target (argument, or registered via `page.set_render_target(target)`). Composes two steps, both callable alone: `page.materialize(mode)` walks and keeps the result in `page.materialized[mode]`, `finalize` delivers it. |
| Validate | `page.validate_source()` | Reports the nodes whose minimum child cardinality is unmet: `(fullpath, [missing tags])` per node, empty list when the document is complete. Rendering never implies it — the author asks. |

The source bag is inspectable as `page.source` after `create()`.

With data it is the same two phases — `setup` seeds the store, the
pointers read it:

```python
page = CustomerPage(name="customer")
page.create()               # setup(data) + main(source) + data-elements
page.render()
```

## Grammar declaration

A builder declares its grammar via decorators on methods:

```python
from genro_builders.builder import BuilderBase, element

class MyBuilder(BuilderBase):

    @element(sub_tags='body')
    def html(self): ...

    @element(sub_tags='h1,p')
    def body(self): ...

    @element(sub_tags='')   # leaf (void element)
    def br(self): ...
```

An unknown item in `sub_tags` raises at class definition time. See
[Decorators](decorators.md) for the full list.

## Grammar documents

A builder class can also declare its grammar in JSON documents, the
`builder_grammar` 1.1 format that `to_grammar()` writes and
genro-builders-js reads. Two class attributes control it:

- `_grammar_documents` — tuple of document paths of this class. A
  relative path is resolved against the directory of the class's
  module. Default `()`.
- `_decorated_elements` — `False` leaves the decorated methods of this
  class out of its grammar. Default `True`.

Neither is inherited: each class states its own.

```python
from genro_builders.contrib.html import HtmlBuilder

class Dialect(HtmlBuilder):
    _name = "dialect"
    _grammar_documents = ("grammars/binding.json",)
```

The class grammar is composed parent first: the parent's grammar, then
the class's decorated methods, then its documents in declared order. A
later definition of an element replaces the earlier one entirely,
without merging parameters, `sub_tags`, `parent_tags`,
`inherits_from`, `ns` or `_meta`: a document of the class overrides a
decorated method of the same name. The data-elements of `BuilderBase`
(`dataSetter`, `dataFormula`, `dataController`) are the first layer, so
a subclass can redefine them with its own signature. The format and
the rule are specified in `GRAMMAR_FORMAT.md` §9, next to
`builder/base.py`.

## Page subclassing

The user defines the page by subclassing the dialect builder and
overriding `main` (and `setup` when the page reads data):

```python
from genro_builders.contrib.html import HtmlBuilder

class CustomerPage(HtmlBuilder):
    def main(self, root):
        root.body().h1("Customer page")
```

## The Source class

The builder declares the `SourceBag` class of its Source in the class
attribute `_source_class`. The default is `SourceBag`. The Source
declares the class of its nodes in `_node_class` (`SourceBagNode` for
`SourceBag`). This is the legacy GenroPy pair `domSrcFactory` /
node class.

```python
from genro_tytx import get_subtype_dict, set_subtype_dict

from genro_builders import SourceBag, SourceBagNode
from genro_builders.contrib.html import HtmlBuilder

class PageNode(SourceBagNode):
    __slots__ = ()

class PageSource(SourceBag):
    _node_class = PageNode

# Only needed for the TYTX wire: "::X" with __cls "PageSource".
set_subtype_dict("X", {**get_subtype_dict("X"), "PageSource": PageSource})

class CustomerPage(HtmlBuilder):
    _source_class = PageSource

    def main(self, root):
        root.body().h1("Customer page")
```

- `_source_class(builder=self)` is instantiated for `_sourceroot`, for
  `source` under `_root_`, for `new_root()` and for the component
  expansion root. A subclass keeps the `SourceBag` constructor
  signature.
- A branch created while authoring, including a scalar node promoted
  to a branch, is an instance of the class of its parent bag.
- On the TYTX wire the Source travels as `::X` with `__cls` set to the
  name under which its class is registered in the subtype dictionary
  of `X`. An unregistered subclass cannot be serialized.

## What lives where

| Concern | Owned by |
|---------|----------|
| Grammar (tags, validation, schema) | Builder class |
| Source bag (the recipe) | Builder instance (`page.source`, under the structural `_root_`) |
| Rendering (string output) | Renderer (`renderer_<mode>` property, fresh per call) |
| Render targets (file, stream, callable; per mode) | Builder instance |
| Node lookup by id | Builder (`node_by_id`, per-builder namespace) |
| Data (one flat datastore, no segments) | Builder instance (`page.data`, `node.data` from any node) |

This separation is fixed by the architecture contract (areas
`BLD` / `PAG`). See `roadmap/architecture-contract.md`.

## What is here, and what is next

Already implemented:

- **Pull-based binding** — `^pointer` / `=pointer` / explicit `:` suffixes resolved
  at render time, with read-time pointer registration (`DAT.2`); data
  presentation via `mask`/`_wdg` (`DAT.5`); named inputs remain independently projected. See [migration](pointer-suffixes.md).
- **Data-elements** — `dataSetter`, `dataFormula`, `dataController`
  (plain `@element` marked as data). All three compute during `create()`,
  once, in document order: see [Decorators](decorators.md).
- **Components** — `@component` (render-time ephemeral expansion,
  `iterate` over a collection) and `@container` (generates real source
  at call time). See [Components](components.md).

Designed but not yet implemented:

- **`@slot`** (`PAG.6`) — fill-by-id at node birth. See
  `roadmap/component-design.md`.
- **Reactivity** — the document is static: a data change is followed by
  rendering again. Fine-grained reactivity is a separate engine (`RX`),
  still under design.
