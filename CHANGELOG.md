# Changelog

## 0.30.0 — 2026-10-20

- BREAKING: Source identity uses `nodeId` in both Python and JavaScript. Update
  declarations, attribute reads/writes and named metadata templates together.
- Preserve identity lookup, duplicate detection, symbolic paths and the separation
  from DOM `id`; identity metadata is not rendered into markup.
- No `node_id` alias or serialized-Source conversion. Regenerate saved Source
  and upgrade producing/consuming applications together.
- Keep `node_label`, `node_position`, `target_id` and language-specific method
  names unchanged. Require the verified TYTX 0.16.3 release.

## 0.29.0 — 2026-10-17

- Support portable TYTX dtype annotations, retaining registered type identity,
  strict scalar validation and nullability through nested signatures.
- Add explicit pointer suffix templates (`:`) and typed expression slots (`:=`).
  Static output leaves expressions inert; JS consumers provide the compiler hook.
- BREAKING: ordinary `${name}` attribute text stays literal and no longer consumes
  helper attributes. Migrate `width="${w}px", w="^width"` to `width="^width:{}px"`.
- Expose suffix dependency discovery; preserve referenced attributes and authored
  Source. Strip suffixes from lookup/subscription paths and retain symbolic
  attribute selectors. Grammar collection-key templates stay supported.
- Gramlot adoption, compiler integration and downstream publication remain a
  separate consumer task. See the pointer-suffix migration guide.


## 0.28.0 — 2026-10-13

- Add `CustomTypes.register(name, type, annotation)` and named aliases in signatures.
- Share Regex/Range definitions through the 1.2 grammar catalog; keep loading and
  exporting legacy 1.1 grammars without named types. Reject catalog name conflicts.
- Recheck registered constraints before resolving or discovering Source pointers,
  including deserialized Source, and during explicit Source validation.
- Verify current stable Genro dependencies and raise their Python minimum versions.

## 0.27.0 — 2026-09-29

- A builder class declares its JSON grammar documents (`builder_grammar` 1.1)
  in `_grammar_documents`; `_decorated_elements` (default `True`) says whether
  its decorated elements are used. Grammars compose along the MRO, parent
  first; within a class the documents come after the decorated elements and
  override them (#50).
- A redefined element or abstract replaces the earlier definition entirely;
  nothing merges. The BuilderBase data-elements are the first layer, so a
  dialect can redefine `dataSetter`, `dataFormula` and `dataController` (#50).
- The grammar export writes version 1.1. The document loader applies the
  validations of genro-builders-js 0.4.0: strict JSON primitives, required as
  presence, nullable annotations, finite JSON, abstract cycles, `parent_tags`
  and `sub_tags` syntax, regex portability (#50).
- The datastore has a stable root, as the Source: a private wrapper
  `_dataroot` with the content node `_root_` (`DATA_ROOT`). `builder.data`
  stays the content Bag, so author paths do not change. Sub-builders share the
  content and the wrapper; the builder exposes no subscription (#37).

## 0.26.0 — 2026-09-28

- Contract change: `${name}` templates expand only inside the attributes of
  non-data elements, the rule of genro-builders-js 0.3.0. The node value is not
  a template: `div("Ciao ${n}", n="^nome")` renders
  `<div n="Mario">Ciao ${n}</div>`. Data-element attributes (dataSetter,
  dataFormula, dataController) are never templates.
- `\${name}` stays the literal text `${name}`.
- A name that is not a resolved attribute raises
  `ValueError("Unknown template parameter 'name'")`, the message of JS.
- HTML: a string node value ending in `::HTML` is emitted as raw markup,
  without the suffix.
- Examples 07_address_block and 08_component_store compose ZIP and city with
  one span each.

## 0.25.0 — 2026-09-28

- A builder declares the SourceBag class of its Source in the class attribute
  `_source_class` (default `SourceBag`), as the legacy GenroPy page declares
  `domSrcFactory`. It is used for `_sourceroot`, `source`, `new_root()` and the
  component expansion root. genro-builders-js 0.3.0 uses `_sourceClass`.
- Branches created while authoring, including a promoted scalar node, follow
  the class of their parent bag; now covered by contract tests.
