# Custom types

`CustomTypes` centralizes named constraints and hides `Annotated` from authoring
code. Define an application module such as `custom_types.py`:

```python
from genro_builders import CustomTypes
from genro_builders.builder import Regex, Range

ct = CustomTypes()
ct.register("no_pointer", str, Regex(r"(?![\^=])[\s\S]*"))
ct.register("code", str, Regex(r"[A-Z]{2}[0-9]{4}"))
ct.register("positive", int, Range(ge=1))
```

Then use registered aliases in signatures, including deferred annotations:

```python
from my_app.custom_types import ct
from genro_builders import BuilderBase
from genro_builders.builder import element

class ContactBuilder(BuilderBase):
    @element()
    def contact(self, method: ct.no_pointer, code: ct.code, record_id: str = ""): ...
```

`register(name, type, annotation)` returns the alias as well as publishing it
under `ct.name`. Names are public ASCII identifiers, excluding Python keywords
and registry/prototype API names. Duplicate names and unknown Python attributes
raise errors. Register before signature introspection. Dynamically registered
attributes have limited IDE completion and static type-checker support.

`ct.validate("code", value)` applies a constraint explicitly, for example inside
a handwritten helper. `ct.to_dict()` returns independent JSON-compatible data;
`CustomTypes.from_dict(catalog)` restores a registry without importing code.

## Original input and pointers

Registered constraints apply to **original input**. `ct.no_pointer` rejects
strings starting with `^` or `=`, including `==`; it allows empty and multiline
literal strings. Plain `str` keeps its existing behavior in pointer-capable
paths. Registered types do not describe the type of a pointer's resolved value.
An email/code validator checks the supplied string, not a later resolved value.

The builder checks named constraints at authoring and again before runtime
resolution, before `node.pointers()` exposes reactive bindings, and during
`validate_source()`. The latter still reports missing child cardinalities but
raises on invalid registered input. These checks also cover a deserialized or
subsequently edited Source associated with a builder. Ordinary legacy validation
does not become an implicit full render-time validation pass.

A handwritten helper must put the contract on the resulting Source attribute.
For example, if `remote(method)` writes an attribute called `remote`, the target
element must declare `remote: ct.no_pointer` (or load its equivalent grammar
contract). Checking the helper's argument alone cannot protect serialized Source.
This package does not change Gramlot's helpers or enable variable remote methods.

## Python/JavaScript interchange

`BuilderBase.to_grammar(path)` collects referenced named types into a
`custom_types` catalog and emits parameter references such as
`{"kind": "custom", "name": "no_pointer"}`. Documents with a catalog use format
**1.2**. Existing grammars without named types continue to export as **1.1**;
both versions can be loaded. Older consumers must be updated to read 1.2.

The JavaScript `CustomTypes.fromJSON(catalog)` reads the same definitions and
provides `ct.no_pointer` as a reference descriptor. Grammar loading resolves those
references automatically. Catalog names have one meaning throughout a composed
grammar; conflicting definitions fail rather than silently overriding a type.

The initial portable validators are `Regex` on `str` and `Range` on `int` or
`float`, one per registration. Numeric inputs follow the finite JSON domain
(booleans are not numbers). Other base/validator combinations cannot be exported.
Python-only callable validators work locally but cannot be exported. Definitions
cannot depend on another registered type, and registered aliases cannot be
re-annotated; reuse them directly, in optional unions, or as collection items.

Regex matching covers the **whole string** in both languages. Use the documented
portable subset of the grammar format. In particular, `\w`, `\d`, standalone
`\s` and their complements have differing Unicode semantics and are rejected;
use explicit character ranges. The universal character class `[\s\S]` is
supported because its union has the same meaning in both engines. Case-insensitive
matching, word boundaries, backreferences, inline flags, possessive quantifiers
and Python-specific regex constructs are not portable. Dot and line anchors
retain Python's LF-based line semantics in JavaScript, including Unicode input. Do not assume a
regex checks semantic validity, such as an email domain or a fiscal-code checksum.

See the [grammar format](../../src/genro_builders/builder/GRAMMAR_FORMAT.md)
for the catalog schema and version rules.
