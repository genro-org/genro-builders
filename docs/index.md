# genro-builders

**Last Updated**: 2026-07-27
**Status**: 🟢 APPROVATO — allineato al contratto v0.9.0.

Builder system for [genro-bag](https://github.com/genropy/genro-bag).
Construct structured documents — HTML, SVG, CSS, XML dialects —
through a fluent, validated Python API.

## What ships today

Dialects under `genro_builders.contrib`, plus the XML core:

| Grammar | Module | Notes |
|---------|--------|-------|
| HTML5 | `genro_builders.contrib.html` | 112 elements from the W3C schema |
| SVG | `genro_builders.contrib.svg` | 60+ elements |
| CSS | `genro_builders.contrib.css` | Level 1 (rules, selectors, vars, `@media`/`@supports`/`@import`) |
| XSLT | `genro_builders.contrib.xslt` | XSLT 1.0 stylesheets written pythonically; HTML5 vocabulary mixed in as literal result elements |
| Config | `genro_builders.contrib.config` | Configuration trees with distributed grammars (`app:grammar` mounts) + the callable `ConfigHandler` read door |
| XML / XSD | `genro_builders.xml` | `XmlBuilderBase` shared grammar base + transpiler: an XSD schema becomes a `<Dialect>Builder` you commit and import (bundled Sitemap and FatturaPA examples) |

The live application layer (server-side SPA over websocket, the
effective widget collections, script `genro-ws-live`) lives in its own
project: **genro-ws-web**, built on genro-builders.

## Where to start

- **[Getting started](getting-started.md)** — first page in 5 minutes.
- **[Builders overview](builders/overview.md)** — what a builder is,
  how the lifecycle works, where the data lives.
- **[Decorators](builders/decorators.md)** — `@element`, `@abstract`,
  sub-builders, and the data-elements.
- **[Custom types](builders/custom-types.md)** — reusable named constraints shared with JavaScript.
- **[Pointer suffixes and dtype migration](builders/pointer-suffixes.md)** — explicit transforms and portable type identities.
- **[Components](builders/components.md)** — `@component` and
  `@container`: reusable grammar, the three calling forms.
- **[Common patterns](builders/patterns.md)** — `._` chaining,
  `node_by_id`, render targets.
- **Grammars** — per-grammar reference:
  [HTML](grammars/html.md), [SVG](grammars/svg.md),
  [CSS](grammars/css.md), [Config](grammars/config.md),
  [XSD dialects](grammars/xsd.md). The XSLT
  dialect ships without a reference page yet: its grammar and the
  transpiler live in `src/genro_builders/contrib/xslt/`.

## In-flight design

Documents describing where the project is heading — not yet shipped
in code — live in `roadmap/` at the repo root:

- `roadmap/architecture-contract.md` — the architectural contract
  (v0.9.0, in vigore dal 2026-07-26).
- `roadmap/component-design.md` — the component design record.
- `roadmap/data-architecture.md` — the data model (pointers, datapath).
- `roadmap/implementation-roadmap.md` — the open-work map.
- `roadmap/documentation-guide.md` — how to write docs.
- `roadmap/history.md` — project timeline.

## Status of the current scaffold

This documentation skeleton describes the framework as it exists
**today**: pull-based binding resolved at render time (`DAT.2`),
data presentation (`mask`/`_wdg`, `DAT.5`), data-elements at the first
calculation (`DAT.4`), one flat datastore owned by the builder (`BLD`),
and components (`@component`/`@container`). The
document is STATIC: a data change is followed by rendering again.
Features still under design — `@slot`, the data-element recompute,
fine-grained reactivity as a separate engine (`RX`) — live in `roadmap/`
and will move to `docs/` when they ship.

```{toctree}
:hidden:
:caption: Getting started

getting-started
```

```{toctree}
:hidden:
:caption: Builders

builders/overview
builders/decorators
builders/custom-types
builders/pointer-suffixes
builders/components
builders/patterns
```

```{toctree}
:hidden:
:caption: Grammars

grammars/html
grammars/svg
grammars/css
grammars/config
grammars/xsd
```
