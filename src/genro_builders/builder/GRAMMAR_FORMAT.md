# `builder_grammar` v1.1 / v1.2 — format specification

**Last Updated**: 2026-10-13
**Status**: 🔴 DA REVISIONARE — documento non ancora approvato
**Format versions**: 1.1 (legacy), 1.2 (named custom types)

---

## 1. Purpose

The `builder_grammar` format is the **runtime contract** between a
Python builder (the producer, via `BuilderBase.to_grammar(path)`)
and any consumer that needs to reconstruct the same grammar in a
different environment:

- the **JavaScript builder** (genro-builders-js), which has no Python
  decorators and builds its class schema from JSON documents
  (`defineGrammar`, the equivalent of Python's `__init_subclass__`);
- the **Python loader**: a builder class names its documents in
  `_grammar_documents` and `__init_subclass__` composes them into
  `_class_schema` (§9);
- any downstream transpiler (JSON Schema, XSD, RELAX NG) that needs
  a neutral starting point.

The format is therefore **language-neutral**: it must be readable
and reconstructible without any Python-specific machinery. It is
**not** an interchange format with foreign ecosystems: the
vocabulary (`element`, `abstract`, `subbuilder`, `sub_tags` /
`parent_tags` cardinality, `inherits_from`) is the vocabulary of
the Genro builder system. A consumer that does not understand
those concepts cannot use the document — and that is by design.

---

## 2. File extension and identification

| Aspect | Convention |
|---|---|
| File extension | `.json` (plain JSON). Recommended basename matches `grammar.name`, e.g. `html.json`, `svg.json`. |
| Identification by **content** | The very first key of the document is `document_format`, whose `name` field equals `"builder_grammar"`. |
| MIME type (internal) | `application/vnd.genro.builder-grammar+json` (Genro convention, not IANA-registered). |

Content-based identification is the canonical way for tools to
recognize a `builder_grammar` document. The file name is a
convention, not a contract.

---

## 3. Document structure

A `builder_grammar` document is a JSON object with **four top-level
required keys**, always present, in this exact order. Version 1.2 may also
carry `custom_types` (§4.4):

```json
{
  "document_format": {"name": "builder_grammar", "version": "1.1"},
  "grammar": {
    "name": "html",
    "version": null,
    "title": null,
    "description": null
  },
  "abstracts": { ... },
  "elements":  { ... }
}
```

Sub-builders and data-elements are **not** separate sections: they are
ordinary elements marked in their `_meta` (`_meta.subbuilder` for a
dialect boundary, `_meta.data_element` for a data-element). They appear
in the `elements` section like any other element, distinguished only by
that `_meta` marker (see §4.2).

### 3.1 `document_format`

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Always `"builder_grammar"`. Identifies the format. |
| `version` | string | Format version, `"1.1"` or `"1.2"`. Independent from `grammar.version`. Other versions are refused. |

`document_format` is **always the first key** of the document.

### 3.2 `grammar`

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Canonical name of the grammar (e.g. `"html"`, `"svg"`, `"css"`). Comes from `BuilderBase._name`. |
| `version` | string \| null | Version of this specific grammar (e.g. `"5.2.0"` for HTML5 revision 2). Optional. |
| `title` | string \| null | Human-readable title. Optional. |
| `description` | string \| null | Long-form description. Optional. |

Optional metadata fields are **present** in the document with
`null` value, not omitted. The document shape is stable.

### 3.3 Two sections, in usage order

| Section | Contents |
|---|---|
| `abstracts` | Abstract templates that define shared `sub_tags` / `parent_tags`. Consumed by `inherits_from`. Always emitted first because elements reference them. |
| `elements` | Every instantiable, schema-validated element of the grammar — including sub-builder entry points (`_meta.subbuilder`) and data-elements (`_meta.data_element`), which are ordinary elements with a marker, not a separate section. |

Each section is a JSON object (not an array). Keys are element
names; values are the per-element form described in §4. **Both
sections are always present** even when empty (`{}`).

The sections are emitted in this order because a top-down reader
(e.g. the JavaScript bootstrap) wants to know the abstracts before
it processes the elements that inherit from them.

---

## 4. Per-element form

The shape of each per-element entry is fixed. The exporter writes
every key, missing values as explicit `null`. A consumer accepts an
entry that omits keys and reads them as `null`; it refuses an unknown
key.

### 4.1 Abstract

```json
{
  "doc": "Flow content (block-level).",
  "sub_tags": "p,div,section",
  "parent_tags": null,
  "inherits_from": null,
  "ns": null,
  "attributes": null,
  "_meta": null
}
```

| Key | Type | Meaning |
|---|---|---|
| `doc` | string \| null | Documentation text (from the Python docstring of `@abstract`). |
| `sub_tags` | string \| null | Cardinality string for valid children. See §5. |
| `parent_tags` | string \| null | Cardinality string for valid parents. See §5. |
| `inherits_from` | string \| null | Comma-separated names of other abstracts (e.g. `"phrasing"` or `"phrasing,flow"`). **Literal, not resolved.** |
| `ns` | string \| null | Namespace prefix of the emitted tag (`@element(ns=...)`). |
| `attributes` | object \| null | Signature of the `@abstract` method. See §4.3. |
| `_meta` | object \| null | Pass-through metadata for renderers/compilers. No validation. |

### 4.2 Element

```json
{
  "doc": "Hyperlink.",
  "sub_tags": "a,abbr,b,em,strong",
  "parent_tags": null,
  "inherits_from": null,
  "ns": null,
  "attributes": {
    "parameters": [
      {"name": "kwargs", "kind": "var_keyword", "role": "attribute",
       "annotation": null, "has_default": false}
    ],
    "accepts_var_keyword": true,
    "accepts_var_positional": false
  },
  "node_label": null,
  "collection_key": null,
  "_meta": null
}
```

| Key | Type | Meaning |
|---|---|---|
| `doc` | string \| null | Documentation text. |
| `sub_tags` | string \| null | Cardinality string for valid children. See §5. |
| `parent_tags` | string \| null | Cardinality string for valid parents. See §5. |
| `inherits_from` | string \| null | Comma-separated names of abstracts to inherit from. **Literal, not resolved.** See §6. |
| `ns` | string \| null | Namespace prefix of the emitted tag (`@element(ns=...)`). |
| `attributes` | object \| null | Signature of the element: its parameters. See §4.3. `null` declares no signature: every attribute is accepted, none is required. |
| `node_label` | string \| null | Default node label of a singleton element (`@element(node_label=...)`). |
| `collection_key` | string \| null | Child attribute or `${...}` template that labels the children (`@element(collection_key=...)`). |
| `_meta` | object \| null | Pass-through metadata. Also the **marker** that distinguishes special elements (see below). |

#### Sub-builders and data-elements via `_meta`

A sub-builder and a data-element are ordinary elements; what marks them
is a key in `_meta`, not a dedicated section or shape:

- **Sub-builder** — `_meta.subbuilder` declares the grammar the node
  switches to, in one of two string forms:

  - **Registry name** (no colon) — the canonical name of a registered
    grammar (matches some other `grammar.name`):

    ```json
    {
      "doc": "Embedded SVG drawing.",
      "sub_tags": "*",
      "parent_tags": null,
      "inherits_from": null,
      "ns": null,
      "attributes": null,
      "node_label": null,
      "collection_key": null,
      "_meta": {"subbuilder": "svg"}
    }
    ```

  - **Parameter reference** (`kwarg:attr`) — the grammar comes from the
    call site: the value the recipe passes as `kwarg` carries the
    grammar class in its `attr` attribute
    (`_meta": {"subbuilder": "app:grammar"}`). The kwarg left unset
    (or passed as `null`/`None`) means **no switch**: the node keeps
    the host dialect and, being marked as a sub-builder, stays
    transparent to containment — it does not police its children: a
    child tag unknown to the host grammar raises, a host-grammar child
    is accepted.

    **No reconstruction promise (v1.x).** The reference is exported
    verbatim as a plain string; a consumer cannot resolve `app:grammar`
    without the Python class the recipe passes at runtime. A consumer
    reading the document knows *that* the element mounts a
    caller-supplied grammar, not *which* one.

  The boundary envelope, when present, rides on `_meta` too
  (`_meta.render_tag` for the host-side wrap tag, `_meta.render_attributes`
  for the framework attributes emitted on it).

- **Data-element** — `_meta.data_element` marks an element that binds
  data-infrastructure (a tabular section, a setter/formula/controller).
  It is transparent at render time; binding details are not part of the
  neutral grammar contract.

  ```json
  {
    "doc": "Bind a tabular section.",
    "sub_tags": "",
    "parent_tags": null,
    "inherits_from": null,
    "ns": null,
    "attributes": null,
    "node_label": null,
    "collection_key": null,
    "_meta": {"data_element": "setter"}
  }
  ```

A consumer that does not recognise a `_meta` marker still sees a valid
element entry; the marker is additive information, not a different shape.

### 4.3 `attributes` — the signature

`attributes` describes the parameters of the declaring method, in
order, `self` excluded:

| Key | Type | Meaning |
|---|---|---|
| `parameters` | array | One object per parameter (below). |
| `accepts_var_keyword` | boolean | A parameter has kind `var_keyword` (`**kwargs`): the attribute set is open. |
| `accepts_var_positional` | boolean | A parameter has kind `var_positional`. |

The two flags must agree with `parameters`; a consumer that finds them
absent computes them from `parameters`.

Each parameter:

| Key | Type | Meaning |
|---|---|---|
| `name` | string | Identifier, unique in the list. |
| `kind` | string | `positional_only`, `positional_or_keyword`, `keyword_only`, `var_positional`, `var_keyword` (Python `inspect.Parameter.kind`, lowercase). |
| `role` | string | `framework` (a build-time parameter such as `node_tag`, not an attribute), `value` (`node_value`, the node value), `attribute`. |
| `annotation` | object \| null | Type descriptor (below). `null`: no annotation, no type check. |
| `has_default` | boolean | The parameter has a default: it may be omitted. |
| `default` | JSON value | Present if and only if `has_default` is `true`. |

A non-variadic `attribute` or `value` parameter without default is
**required**, by presence: an explicit `null` is a supplied value,
accepted only by a nullable annotation: no annotation, `any`,
`NoneType`, `builtins.object`, a literal listing `null`, a union with
such a member, an `annotated` whose base accepts it and whose metadata
holds no `range` / `regex` (e.g. `Optional[Annotated[int, Range(ge=1)]]`
accepts `null`, `Annotated[int, Range(ge=1)]` does not). JSON `true` / `false` are not numbers:
they fail `int` and `float`. The Python loader applies these rules,
taken from genro-builders-js 0.3.1, to the signatures it reads; a
decorated signature keeps the Python rules (`None` counts as missing,
`bool` is an `int`). A consumer reading a document (the Python loader,
genro-builders-js) skips the first positional non-framework parameter
of a component (`_meta.component`): it is the expansion root, supplied
by the renderer.

Type descriptors, by `kind`:

| `kind` | Fields | Python type |
|---|---|---|
| `any` | — | `Any` |
| `type` | `module`, `name` | A named type. Portable: `builtins.str`, `int`, `float`, `bool`, `list`, `dict`, `tuple`, `set`, `object`, `NoneType`, and `collections.abc.Callable`. |
| `union` | `items` (descriptors) | `A \| B` |
| `literal` | `values` (JSON values) | `Literal[...]` |
| `generic` | `origin` (a `type`), `arguments` (descriptors) | `list[...]`, `dict[...]`, `tuple[...]`, `set[...]` |
| `ellipsis` | — | `...` inside `tuple[T, ...]` |
| `annotated` | `base` (descriptor), `metadata` (array) | `Annotated[base, ...]` |

`annotated` metadata items: `{"kind": "regex", "pattern", "flags"}`
(`Regex`), `{"kind": "range", "ge", "le", "gt", "lt"}` (`Range`, every
bound present, `null` when unset), `{"kind": "value", "value"}` (plain
JSON metadata, no validation).

The exporter raises `TypeError` on an annotation with no descriptor
(a class defined in a function, callable metadata other than `Regex` /
`Range`) and on a default or `_meta` value that JSON cannot carry
losslessly (an object, a non-finite float, a tuple, a non-string dict
key). `to_grammar` builds the whole document before it opens the file,
so a failed export leaves an existing file unchanged. An empty `_meta`
is exported as `{}`, a missing one as `null`. The Python loader
refuses a `type` outside the portable list: a document never makes it
import a module.

---

### 4.4 Named custom types (version 1.2)

A 1.2 document may add a top-level `custom_types` object. Each name maps to
an `annotated` definition with `base` and exactly one portable `regex` or
`range` metadata descriptor. Portable pairs are Regex/`builtins.str` and
Range/`builtins.int` or `builtins.float`, with finite JSON numeric inputs.
Other combinations are rejected. For example:

```json
{
  "custom_types": {
    "no_pointer": {
      "kind": "annotated",
      "base": {"kind": "type", "module": "builtins", "name": "str"},
      "metadata": [
        {"kind": "regex", "pattern": "(?![\\^=])[\\s\\S]*", "flags": 0}
      ]
    }
  }
}
```

A parameter refers to this definition using
`"annotation": {"kind": "custom", "name": "no_pointer"}`. References also
work in optional unions and generic collection arguments. Definitions cannot
reference other catalog entries. Unknown references and conflicting definitions
of one name in composed grammars are errors; equal definitions may be shared.
No consumer imports Python modules or executes serialized callbacks.

Catalog names are public ASCII identifiers, beginning with a letter. Python
keywords, registry API names (`register`, `validate`, `resolve`, `to_dict`,
`from_dict`, `toJSON`, `fromJSON`) and Object prototype names are reserved.

All named constraints have **input validation semantics**: check the original
value, before pointer interpretation/resolution and before exposing reactive
pointers for subscription. This is fixed by the `custom` descriptor kind; no
separate validation-stage field is needed in this version. It is not a
resolved-value contract. Check Source loaded from serialization against its
owning grammar as well as Source built through helpers. The check is repeated
before runtime resolution and in explicit Source validation.

For `no_pointer`, leading `^` and `=` are forbidden (`==` is covered by `=`).
Empty and multiline literal strings remain valid. No global permission change
is applied to plain string parameters. Handwritten helpers must map argument
contracts onto the actual Source attribute declaration; annotating only a
helper's argument does not provide a serialized Source contract.

Regex uses full-string matching. The existing non-portable character-class and
flag restrictions still apply; the exact idiom `[\s\S]` is additionally supported
as a universal character class. Neither `\s` nor `\S` is portable individually.
Word boundaries, backreferences, inline flags, and possessive quantifiers are
also rejected. JS translates dot and line anchors to Python LF semantics,
rather than interpreting CR/U+2028/U+2029 as extra line boundaries.

Catalog presence requires 1.2. Catalog omission in 1.2 means an empty registry.
Existing 1.1 documents remain accepted and cannot carry a catalog. Python export
uses 1.2 when named types are present and retains 1.1 otherwise. JavaScript
composition preserves 1.2 when either document uses it, including when a later
legacy document extends a grammar with registered types. Older readers reject
1.2 explicitly instead of silently discarding the constraints.


## 5. `sub_tags` / `parent_tags` grammar

The `sub_tags` and `parent_tags` fields are **strings** that
declare child / parent constraints with cardinality. The format is:

```
<spec>      ::= <item> ("," <item>)*
<item>      ::= <name> <cardinality>?
<name>      ::= identifier   |  "*"
<cardinality> ::= "[" <min> ":" <max> "]"
                |  "[" <n> "]"
                |  "[]"
<min>       ::= integer | ""
<max>       ::= integer | "*" | ""
<n>         ::= integer
```

Semantics:

| Spec | Meaning |
|---|---|
| `""` (empty) | Leaf element. No children allowed. |
| `"*"` | Wildcard. Any children allowed, any number of times. |
| `"foo"` | Exactly one `foo` (default cardinality `[1:1]`). |
| `"foo[]"` | `foo` zero or more times (i.e. `[0:*]`). |
| `"foo[2]"` | Exactly two `foo`. |
| `"foo[2:5]"` | Two to five `foo`. |
| `"foo[1:*]"` | One or more `foo`. |
| `"foo,bar[]"` | Exactly one `foo`, plus zero or more `bar`. |

This is the same grammar used internally by `_parse_sub_tags_spec`
in `_grammar.py`. The spec is reproduced here so that the document
is self-contained: a consumer does not need to read Python source
to understand `sub_tags`.

---

## 6. `inherits_from` semantics

`inherits_from` is exported **literally**, as declared by the
grammar author. Examples:

```json
{"inherits_from": null}                  // no inheritance
{"inherits_from": "phrasing"}            // single parent
{"inherits_from": "phrasing,flow"}       // multiple parents
```

The document does **not** expand the inheritance: the inherited
`sub_tags` are not folded into the inheriting element. The
**consumer** is responsible for computing the transitive closure if
it needs it.

Rationale: consumers vary. A JavaScript builder may prefer the
closure to be pre-computed; a JSON Schema transpiler benefits from
the raw `inherits_from` (which becomes `allOf` in JSON Schema or
`xs:extension base` in XSD). Keeping the document literal pushes
the decision to the consumer.

**Invariant guaranteed by the exporter**: every name in
`inherits_from` resolves to an existing key in `abstracts`. The
exporter validates this at class-definition time in Python's
`__init_subclass__`. Consumers can therefore assume that
`inherits_from` references are never dangling. If a consumer
encounters a dangling reference, the document is malformed —
report it as a producer bug.

---

## 7. Section ordering and topological sort

### 7.1 Top-level sections

The four top-level keys appear in this exact order:

1. `document_format`
2. `grammar`
3. `abstracts`
4. `elements`

Rationale: a top-down reader processes definitions before usages.
`abstracts` define contracts; `elements` reference them (and carry
sub-builders and data-elements as `_meta`-marked entries).

### 7.2 Inside each section

Within each section, keys are emitted in **topological order**
relative to `inherits_from` dependencies, with insertion-order from
the source class schema as the secondary key.

For `abstracts`, this means an abstract like `flow` that declares
`inherits_from: 'phrasing'` appears **after** `phrasing` in the
section.

For `elements`, in practice today, elements inherit only from
abstracts (which live in a different section), so the topological
constraint inside `elements` collapses to insertion-order.

The guarantee is: **for any key K in a section, every name in
K's `inherits_from` either lives in another section that came
earlier (i.e. `abstracts`), or lives in the same section at an
earlier index**.

---

## 8. Versioning and evolution

Two independent versions live in the document:

- **`document_format.version`** — the version of **this format**.
  Bumped when the structure changes (additive in `v1.x`, breaking
  in `v2.0`). Consumers should check this before parsing.
- **`grammar.version`** — the version of the **specific grammar
  being described**. Bumped when the grammar itself evolves (e.g.
  HTML5.2 → HTML5.3). Independent from format version.

A producer is responsible for emitting `document_format.version`
that matches the format actually used. A consumer is responsible
for checking it and refusing documents with unsupported versions.

---

## 9. Grammar documents on a builder class

A builder class declares its grammar with decorators, with JSON
documents, or with both. Two class attributes of `BuilderBase`
control it:

| Attribute | Default | Meaning |
|---|---|---|
| `_grammar_documents` | `()` | Tuple of paths of v1.1 documents of THIS class. A relative path is resolved against the directory of the module that defines the class. The documents override the class's decorated methods. |
| `_decorated_elements` | `True` | `False`: the decorated methods of THIS class (`@element`, `@abstract`) do not enter its grammar. They are still removed from the class. |

Both are read from the class's own namespace: a subclass does not
inherit them.

```python
from genro_builders.contrib.html import HtmlBuilder

class Dialect(HtmlBuilder):
    _name = "dialect"
    _grammar_documents = ("grammars/binding.json",)
```

`__init_subclass__` builds `_class_schema` in layers, each applied on
top of the previous one:

1. the grammar of the parent builder class; a direct subclass of
   `BuilderBase` starts from the data-elements declared on
   `BuilderBase` (`dataSetter`, `dataFormula`, `dataController`);
2. the class's decorated methods, unless `_decorated_elements` is
   `False`;
3. the class's `_grammar_documents`, in declared order.

The grammar of a class is therefore composed along the class chain,
parent first, as `defineGrammar` composes it in genro-builders-js.

**Replace rule.** When a layer defines an element (or an abstract)
that an earlier layer defines, the new entry replaces the earlier one
entirely: parameters, `sub_tags`, `parent_tags`, `inherits_from`,
`ns`, `doc`, `node_label`, `collection_key`, `_meta`. Nothing is
merged; a key the new entry leaves `null` stays `null`. Elements not
named by the layer are inherited unchanged. The data-elements follow
the same rule: a subclass redefines `dataSetter` with its own
signature, e.g. `dataSetter(destination_path, value=None, **attr)`.

A name declared both by a decorator and by a document of the same
class is not an error: the document's entry replaces the decorator's
entirely, by the same rule. A malformed document raises `ValueError`
naming the file and the field. Besides the shape of every key, the
loader checks what genro-builders-js 0.3.1 checks: finite JSON numbers
only (`NaN`, `Infinity` refused), `parent_tags` names that are
identifiers without duplicates, unique parameter names, variadic flags
that match the parameters, regular expressions that compile and are
portable (flags limited to `MULTILINE`, `DOTALL`, `UNICODE`; no
`IGNORECASE`; no `\A \Z \w \W \d \D \s \S`, `(?P<`, `(?P=`, `(?P!`, `(?(`,
`(?>`), `sub_tags` without a repeated tag or a maximum below the
minimum.
After all the layers of a class, `__init_subclass__` checks that every
`inherits_from` name exists and that no abstract chain is a cycle.

The export of a class (`to_grammar`) is a v1.1 document that a class
reads back through `_grammar_documents` as the same grammar. The shared
fixtures in `tests/fixtures/class_grammar/` (three input documents and
the two expected composed grammars) are the cross-language contract
with genro-builders-js.

---

## 10. Known limitations of v1.1

- **Abstract signatures**: in Python the `attributes` of an abstract
  are exported and read back, but do not validate the calls of the
  elements that inherit from it. genro-builders-js copies them onto an
  inheriting element whose `attributes` is `null`.
- **No transpiler**: the format is the **source** of downstream
  transpilers (JSON Schema, XSD, RELAX NG) but does not include any
  of them. Transpilers are separate tools.
- **No CLI**: the exporter API is `Class.to_grammar(path)`. A
  command-line tool may be added later.
- **`_meta` is opaque**: the format does not validate `_meta`
  contents. By convention, `_meta` values must be JSON-friendly
  (no callables, no class objects). A producer that includes
  non-JSON values will fail at serialization time with a standard
  `json.dumps` error.

---

## 11. References

- **Producer** (Python): `BuilderBase.to_grammar(path)` in
  [`base.py`](./base.py).
- **Implementation**: [`_grammar_export.py`](./_grammar_export.py).
- **Consumer** (Python): `_grammar_documents`, read by
  [`_grammar_load.py`](./_grammar_load.py).
- **Reference dialects**:
  [`contrib/html/`](../contrib/html/),
  [`contrib/svg/`](../contrib/svg/),
  [`contrib/css/`](../contrib/css/).
- **`sub_tags` parser** (Python reference):
  `_parse_sub_tags_spec` in [`_grammar.py`](./_grammar.py).

---

## Riferimenti

Documento prodotto nella sessione Claude Code locale del 2026-05-19
sul subtask `schema_export` (genro-builders). Riallineato il 2026-06-06
al modello unificato `@element`+`_meta` (sub-builder e data-element non
sono più sezioni separate: due chiavi top-level invece di sei).


## TYTX dtype annotations

Portable signatures may use `{"kind": "dtype", "dtype": "D"}`. The code is the
TYTX type identity (for example T, L, R, B, N, D, H, DHZ, NN or a registered custom
code). Unknown codes fail loading. Python resolves through `SUFFIX_TO_TYPE`; JS
uses `getRegisteredType` and the public Decimal predicate for N. There is no
implicit string parsing or numeric coercion. Existing annotation forms remain
readable. A union combines dtype branches; nullability is an NN branch. JSON
defaults retain the existing finite-JSON contract: dtype is an annotation, not an
alternate encoder for literal defaults.

Python's exporter emits dtype for registered domain annotation classes such as
Decimal/date/time/datetime, while existing primitive annotation descriptors retain
their established representation. Component producers can emit dtype for all
scalar signatures. In JS, D/H/DHZ share Date as their carrier; semantic civil-date
or civil-time constraints belong to the consuming editor. N accepts the current
TYTX Decimal backend without converting it to a Number.
