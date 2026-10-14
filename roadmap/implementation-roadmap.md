# Implementation roadmap — open work

**Last Updated**: 2026-08-04
**Status**: 🟢 ALIGNED with contract v0.9.0, code at 0.23.1.

This document is intentionally **not a plan**. It maps what is open and
how the open pieces depend on each other; it does not pick an order and
does not record decisions. Decisions live in
[architecture-contract.md](architecture-contract.md).

---

## 1. Where the code stands

The static-first core is complete and the areas it closed are no longer
open work. Implemented and covered by tests (340 green at 0.23.1):

- **Data, pull-based** — path grammar, `^`/`=` pointers, `${}` templates
  with consumed inputs, `mask`/`_wdg` presentation, read-time pointer
  registration (`DAT.2`, `DAT.5`, `DAT.6`). A `BagResolver` found as a
  value or as an attribute resolves through `runtime_values`.
- **Datastore** — ONE flat Bag owned by the builder (`builder.data`,
  reachable from any node as `node.data`). `BuilderHandler` is gone
  (`a83e61e`), and with it multibuilder and datastore segmentation.
- **Render subsystem** — universal walk, per-node dialect dispatch, and
  the two steps: `materialize(mode)` keeps its result in
  `materialized[mode]`, `finalize` delivers it. Rendering does not
  validate — `validate_source()` reports on demand (`RND`, `PAG.4`,
  `PAG.7`).
- **Data elements** — `dataSetter`/`dataFormula`/`dataController` as
  marked `@element`, every kind computed once at `create()`, in document
  order (`DAT.3`, `DAT.4`).
- **Components** — `@component` in its three calling forms
  (single/store/iterate, fractal composition) and `@container`
  (`CMP.9`): the body runs once and writes real nodes the caller fills.
- **Sub-builders** — `@element` marked `subbuilder`, including the
  parameter-reference form `"kwarg:attr"`, where the governing grammar
  arrives as a call-site argument (`BLD.2`).
- **Dialects** — HTML5, SVG, CSS level 1, XSLT 1.0, XSD, and Config
  (`ConfigBuilder` + the callable `ConfigHandler`, four-layer read,
  parent recipes).
- **Grammar export** — `to_grammar(path)` writes the schema as a
  portable document (`_grammar_export.py`, format in
  `src/genro_builders/builder/GRAMMAR_FORMAT.md`).

Retired areas, not open work: `HND` (the handler), `APP` (the
application layer, now genro-ws-web), and the whole push-reactive
apparatus — `live()`, the patch protocol, the render queue, the lazy
lane, derived identity. Where to fish that code out of git is recorded
in [reactivity/removed-machinery.md](reactivity/removed-machinery.md).

## 2. The open axes

### 2.1 Reactive engine (`RX.5`) — research

Fine-grained reactivity is a **separate engine**, not a repair of the
core. The grammar is shared; the static engine EXECUTES the
data-elements while the reactive one carries them. Everything that used
to be listed here as "reactivity granularity" is inside this axis now:
partial re-render off the kept `materialized` result, per-row component
reactivity (`CMP.7`), the data-element cascade (multi-wave compute, ex
"slice 2"), variable datapath and master-detail
([reactivity/variable-datapath.md](reactivity/variable-datapath.md)).
The `roadmap/reactivity/` documents were written against contract
v0.5.0: they are starting material to re-read under `RX.5`, not a
specification to implement.

### 2.2 `@slot(node_id)` (`PAG.6`)

Fill-by-id at node birth. Design complete
([slot-decorator.md](slot-decorator.md)), code absent. The guide case is
a frame whose header/footer panels are filled by the page that mounts
it.

### 2.3 `from_grammar` loader

`to_grammar` writes the schema; nothing reads it back. The loader
reconstructs a builder class from an exported grammar document — the
symmetric half, and the precondition of the JS twin consuming the same
file.

### 2.4 `include_components` (`CMP.6`) — authoring works, render raises

Per-instance grammar enrichment from mixins exists
(`BuilderBase.include_components`) and is documented. `create()` works:
the component enters the instance grammar and the node is written to the
source, covered by `tests/test_include_components.py`. `render()`
raises `AttributeError`.

The two sites were written four days apart and neither knows the other:
`include_components` (`f6751ad`, 2026-06-06) binds the body on the
INSTANCE with `setattr(self, name, obj.__get__(self))`, while the
expansion (`42d4782`, 2026-06-10) reads it from the CLASS in
`renderer/base.py:210`:

    body = getattr(type(builder), node.node_tag).__get__(builder, type(builder))

A `@component` declared on the class or on a base mixin is in the MRO
and expands correctly — that is the path the seven `with_data` examples
take. Only the per-instance one is unreachable from the renderer. The
defect survived because no line of code calls `include_components`,
here or in any downstream repository.

Three ways out, none chosen:

- the renderer reads `vars(builder)` first, then the class — two lines,
  one site, `page.badge` stays the bound body in both cases;
- `include_components` registers in a named instance map the renderer
  reads first — the second place gets a declared purpose, at the price
  of `page.badge` meaning one thing for included components and another
  for declared ones;
- the schema entry carries the function and the renderer asks the
  schema — the only one that leaves a single access point, but it
  touches `__init_subclass__` and puts function objects inside a Bag
  that is deepcopied and elsewhere serialized: to be verified, not
  assumed.

Note that `_pop_decorated_methods` (`_utilities.py:400`) deliberately
leaves components on the class BECAUSE the renderer looks there. That
dependency is written down nowhere else and no test protects it.

The third option of the original entry stands: decide `include_components`
is not part of the surface.

### 2.5 Cross-runtime

"One language, two interpreters": the semantic contract of the source,
the JS twin (bag/builder client-side), golden tests (same recipe → same
tree). Far horizon; constrains design today (named components,
func-by-name, the exported grammar format).

## 3. Smaller open items

Tracked as GitHub issues, each independent of the axes above: collection
re-declaration semantics (#31), the HTML `<label>` tag masked by
`BagNode.label` (#29), inferring `main_tag` for `@component` (#26),
Python→JS transpiling of formulas (#19), `Coerce` in `Annotated`
metadata (#14), optional root-element schema validation (#13), friendly
validation errors (#11).

Documentation gap: the XSLT dialect ships without a reference page under
`docs/grammars/` (its grammar and transpiler live in
`src/genro_builders/contrib/xslt/`).

## 4. Dependency hints

- `RX.5` gates the reactive half of components (`CMP.7`) and the
  data-element cascade; nothing else waits on it.
- `@slot` and `from_grammar` are independent of each other and of
  `RX.5`: both are pure static-core work.
- `from_grammar` gates the cross-runtime axis, which cannot consume a
  grammar nobody can load.
- Downstream consumers (genro-ws-web, genro-textual, genro-print,
  genro-scriba) put real-world pressure on `PAG`/`BLD` and inform the
  preset question left open in the contract.

## 5. What this document is not

- Not a plan: no axis is scheduled.
- Not a commitment: any sentence here frames discussion.
- Not a substitute for the contract: decisions are recorded there (or in
  `component-design.md` for the component record).
