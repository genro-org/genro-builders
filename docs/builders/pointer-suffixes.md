# Pointer suffixes and dtype migration

Available together in Python **0.29.0** and JavaScript **0.6.0**.

## Explicit pointer suffixes

```python
pane.div(width='^width:{}px')
pane.div(width='^w', height='^h:={} * {width}')
pane.div(title='^name:Customer: {?}')
pane.div(readonly='^draft:=!{}')
```

The first `:` separates a `^` (reactive intent) or `=` (passive) pointer
from its suffix. Relative, symbolic and `?attribute` paths retain their normal
meaning. Lookup paths and `node.pointers()` exclude the suffix. `==` is not a
Data pointer. Node text continues to use its ordinary pointer and renderer
format/mask contract; suffixes are an attribute feature.

- `:` composes text. `{}` reads the leading typed Data value; `{name}` reads
  a resolved attribute on the same Source node. Referenced attributes remain
  independently available for projection. A fresh input snapshot is shared
  across the graph, so resolvers are not repeatedly evaluated.
- A null leading value blocks even a constant template. Any participating null
  or empty string blocks the entire template, producing null. `{?}` and `{?name}`
  allow empty strings, but not null. Missing names and cycles are errors even
  when another input is null. Zero and false are valid; boolean text is lowercase.
  Scalar JSON values have shared text semantics; domain objects use their host
  text representation and should use a runtime formatter for portable display.
- `:=` is an expression. Slots pass typed values separately from executable
  source. Null reaches the expression normally. Optional `?` slots are invalid.
  Both static builders return null without executing JavaScript. Authored Source,
  including the complete expression text, remains unchanged and serializable.
- Neither templates nor expression results are interpreted a second time when
  their resulting text begins with `^` or `=`. Ordinary Python Data masks apply
  to bare pointers; transforms read raw typed inputs before presentation masks.

## Runtime integration

JS exports `pointerTransform`, `pointerTemplate`, `pointerExpression` and
`pointerDependencies`. Python exposes `pointer_transform`, `pointer_template`,
`expression_slots` and `pointer_dependencies` in `genro_builders.builder.pointers`.

A JS runtime overrides:

```javascript
evaluatePointerExpression(node, name, raw, expression, inputs) {
    // Invoke the consuming runtime's compiler under its activation/CSP policy.
    return this.compiler.evaluate(expression.text, {_pointerValues: inputs});
}
```

`expression.text` addresses the separately supplied `inputs` through
`_pointerValues[index]`. Never substitute their text into executable code.
The default hook returns null. Builders imports no browser compiler, service,
formatter, or global helper. `_F`, if offered, belongs to the consumer's local
compiler context. Python never evaluates JS code.

The lexical scanner ignores quoted strings, comments, regular expressions and
entire backtick literals (including their interpolation bodies). This is the
existing restricted slot grammar, not a complete JavaScript parser. Empty and
single-name shorthand objects collide with slots: use explicit object members,
e.g. `{pattern: '0.00', mask: '{} €'}`. Identifiers named `_pointerValues` are
reserved by the expression adapter. The runtime compiler validates JS syntax.

`pointerDependencies(node, raw)` returns transitive named Source attributes,
diagnosing missing names and cycles. `${name}` contributes no dependencies.
For reactivity, combine the transformed attribute's leading pointer with those
of its named dependencies. Subscribe only to reactive (`^`) inputs, resolve
paths through `absDatapath`, recompute dependencies on Source rebinding and
unsubscribe on disposal. The base library owns no subscriptions or DOM state;
`runtimeValues` always reads a fresh graph. Widget-specific restrictions such
as disallowing transformed two-way `value` bindings remain with the consumer.

## Breaking migration

```python
# Before: automatic interpolation and implicit helper consumption
pane.div(width='${pixels}px', pixels='^width')
# After: explicit leading pointer, no unnecessary helper attribute
pane.div(width='^width:{}px')
```

Ordinary `${name}` attribute text is now literal, including a preceding
backslash. It performs no lookup, raises no missing-name error and consumes
no attributes. If you retain a helper attribute, it remains in the resolved
attributes. Explicit grammar `collection_key='${code}_${env}'` templates and
JavaScript template literals in scripts are unchanged. There is no compatibility
switch for automatic attribute interpolation.

## Portable dtype signatures

`{"kind":"dtype","dtype":"D"}` identifies a type through the loaded TYTX
registry without importing arbitrary modules or coercing values. Python exports
registered domain classes (date, time, datetime, Decimal, bytes, Bag/custom
classes); existing primitive descriptors remain compatible. Dtype descriptors
retain identity when loaded and re-exported, including legacy `DH`. Unions,
nullable `NN` branches and generic containers retain their validation rules.

Numbers must be finite, booleans are not numbers, and Decimal stays Decimal.
JavaScript D/H/DHZ share a valid Date carrier: civil date/time policy belongs to
the editor. A type code must be registered before grammar loading in each host.
JSON defaults retain the finite-JSON contract; dtype is not a new default-value
encoder. Transport-only registry domains can have host-specific carriers (for
example QS uses the registered object/dict carrier for signature validation).

## Publication and downstream ownership

Publish these two Builder versions first. Gramlot's chat then upgrades both
packages, removes its duplicate pointer suffix implementation and automatic
attribute interpolation, and connects its compiler through the hook. That chat
also owns `_F`, widget-value restrictions, reactive lifecycle/browser tests,
GC-210 updates, examples and the Gramlot release. The Builder release does not
claim that downstream migration is complete; it must precede Gramlot publication.
