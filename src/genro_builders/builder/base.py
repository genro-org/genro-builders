# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""BuilderBase — grammar base class for Bag builders.

A builder declares the grammar of a dialect via decorators
(@element, @abstract), via ``builder_grammar`` 1.1 JSON documents
(``_grammar_documents``), or both, and the schema of valid tag
placements (sub_tags, parent_tags). Sub-builders and data-elements are ordinary
@element marked in their ``_meta`` (no dedicated decorator). The three data-elements
(dataSetter / dataFormula / dataController) are ordinary @element
declared on this base and marked ``_meta['data_element']``. A builder
renders itself: it owns its source (the payload under the structural
``SOURCE_ROOT`` of a wrapper root), the create/render phases, the first
calculation and the per-builder node_id lookup. It also owns the data
store: one flat Bag, ``builder.data``, reachable from any node as
``node.data``. The document is STATIC: a data change is followed by
rendering again — fine-grained reactivity is a separate engine, still
under design (``RX.5``), not this class.

Exports:
    BuilderBase: Base class for all builders.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import re
from abc import ABC
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, ClassVar

from genro_bag import Bag, BagResolver

from ..renderer.xml import XmlRenderer
from ..renderer.yaml import YamlRenderer
from ._decorators import element
from ._grammar import _GrammarMixin
from ._grammar_export import _class_schema_to_grammar_document
from ._grammar_load import _read_grammar_document
from ._utilities import (
    _declaration_signature,
    _extract_signature_info,
    _iter_data_element_methods,
    _parse_sub_tags_spec,
    _pop_decorated_methods,
)
from .source_bag import SourceBag
from .custom_types import _check_custom_type_names
from .target_wrapper import TargetWrapper

# Template token spotted by ``runtime_values`` for ``${name}`` placeholders.
_TEMPLATE_RE = re.compile(r"(\\)?\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

#: Structural key of the source wrapper. It exists only so the source is
#: a tree, not a forest; it is NOT an address. Paths that travel outside
#: the builder are composed relative to ``builder.source``, so this
#: segment never appears in them.
SOURCE_ROOT = "_root_"

#: Structural key of the datastore wrapper, the same shape as the source:
#: ``builder.data`` is the content node under it, so the datastore is a
#: tree, not a forest. It is NOT an address: author data paths are
#: relative to ``builder.data``, so this segment never appears in them.
#: A subscriber on the wrapper sees it as the first element of the
#: pathlist.
DATA_ROOT = "_root_"


def _decorated_schema_attrs(obj: Any, decorator_info: dict[str, Any]) -> dict[str, Any]:
    """Schema-node attributes of a decorated declaration (@element, @abstract)."""
    attrs: dict[str, Any] = {
        "sub_tags": decorator_info.get("sub_tags", ""),
        "parent_tags": decorator_info.get("parent_tags"),
        "inherits_from": decorator_info.get("inherits_from", ""),
        "_meta": decorator_info.get("_meta"),
        "documentation": obj.__doc__,
        "declaration_signature": _declaration_signature(obj),
    }
    # ``ns`` (namespace prefix) is optional: only the elements that
    # declare it carry the attribute, so nodes without a namespace stay
    # clean and the inherits_from merge (``not result[k]``) is never
    # tripped by a spurious ``ns=None``.
    ns = decorator_info.get("ns")
    if ns is not None:
        attrs["ns"] = ns
    if decorator_info.get("abstract", False):
        return attrs
    call_args_validations, declared_names, accepts_var_keyword = (
        _extract_signature_info(obj))
    attrs.update(
        call_args_validations=call_args_validations,
        declared_names=declared_names,
        accepts_var_keyword=accepts_var_keyword,
        node_label=decorator_info.get("node_label"),
        collection_key=decorator_info.get("collection_key"),
    )
    return attrs


def _grammar_document_paths(cls: type) -> list[Path]:
    """Paths of the documents named in ``cls``'s own ``_grammar_documents``.

    A relative path is resolved against the directory of the module that
    defines ``cls``.
    """
    documents = cls.__dict__.get("_grammar_documents", ())
    if isinstance(documents, (str, Path)):
        raise TypeError(
            f"{cls.__name__}._grammar_documents must be a tuple of paths, "
            f"got a single {type(documents).__name__}"
        )
    if not documents:
        return []
    module_dir = Path(inspect.getfile(cls)).parent
    return [module_dir / document for document in documents]


class BuilderBase(
    _GrammarMixin,
    ABC,
):
    """Abstract base class for Bag builders (grammar only).

    A builder declares the dialect via decorators:
        - @element: Pure schema elements (body MUST be empty)
        - @abstract: Define sub_tags for inheritance (cannot be instantiated)

    Sub-builders and the three data-elements (dataSetter / dataFormula /
    dataController) are NOT separate decorators: they are ordinary
    @element marked in their ``_meta`` — ``_meta['subbuilder']`` for a
    dialect boundary, ``_meta['data_element']`` for a data-element. They go
    through the same schema and the same ``_command_on_node`` dispatch as
    any element; the element's ``_meta`` rides onto the node and readers
    query it via ``node._get_meta(...)``. The data-elements are declared on
    this base; ``__init_subclass__`` makes them the first layer of every
    grammar (see ``_iter_data_element_methods``), so a subclass can
    redefine them like any element.

    A class declares its grammar with decorators, with JSON documents
    (``_grammar_documents``), or with both; ``_decorated_elements``
    switches its decorated methods off. See ``GRAMMAR_FORMAT.md`` §9.

    Source, lifecycle phases, render_target, node_id and the data store
    all belong to the builder itself.
    """

    _class_schema: Bag  # Schema built from decorators at class definition

    # -----------------------------------------------------------------------
    # Builder registry (class-level, shared across all dialects)
    # -----------------------------------------------------------------------

    #: Canonical name of this dialect (e.g. ``"html"``, ``"svg"``).
    #: Concrete dialects MUST declare ``_name`` as a class attribute to
    #: appear in :attr:`register`. Builders that leave ``_name = None``
    #: (the default) are not registered — useful for abstract bases
    #: or internal-only classes.
    _name: str | None = None

    #: Class-level dict mapping ``_name`` to the Builder class. Populated
    #: automatically in :meth:`__init_subclass__` whenever a subclass
    #: declares ``_name``. Lookup via :meth:`get_builder_class`. Named
    #: ``_registry`` (not ``register``) to avoid shadowing the
    #: ``ABCMeta.register`` virtual-subclass method inherited via ABC.
    _registry: ClassVar[dict[str, type]] = {}

    #: Builder classes fabricated from grammar mixins (class-level, shared
    #: across all dialects): one ``(mixin, BuilderBase)`` subclass per
    #: grammar class, built lazily by :meth:`get_subbuilder` when a
    #: ``kwarg:attr`` subbuilder reference resolves to a class. Fabricated
    #: classes declare no ``_name`` of their own, so they never touch
    #: :attr:`_registry`.
    _grammar_builders: ClassVar[dict[type, type]] = {}

    #: Case-insensitive tag map (lowercase key -> canonical label), rebuilt
    #: per subclass in :meth:`__init_subclass__`. Declared here so the type
    #: is known at class scope (it cannot be annotated on the ``cls`` target).
    #: Not a ClassVar: ``__init__`` binds it onto each instance as well.
    _schema_tag_names: dict[str, str]

    #: @container dispatch map (lowercase dispatch name -> attr name),
    #: rebuilt per subclass in :meth:`__init_subclass__`. A container is
    #: a callable block invocable from any node (``node.card(...)``); the
    #: dispatcher resolves it through the active builder (legacy
    #: gnrwebstruct parity).
    _containers: dict[str, str]

    #: The ``SourceBag`` class of this builder's Source (legacy GenroPy
    #: ``domSrcFactory``): the builder declares the class of the Source,
    #: the Source declares the class of its nodes (``_node_class``). It is
    #: instantiated for ``_sourceroot``, for the ``source`` payload under
    #: ``SOURCE_ROOT``, for :meth:`new_root` and for the component
    #: expansion root, always as ``_source_class(builder=self)``. Branches
    #: created while authoring follow the class of their parent bag.
    #: Redefine it on a subclass to use a ``SourceBag`` subclass; to
    #: travel on the TYTX wire, the subclass must be registered in the
    #: genro-tytx subtype dictionary of ``X``.
    _source_class: ClassVar[type[SourceBag]] = SourceBag

    #: The ``builder_grammar`` 1.1 JSON documents of THIS class, as a
    #: tuple of paths; a relative path is resolved against the directory
    #: of the class's module. ``__init_subclass__`` applies them in
    #: declared order on top of the parent's grammar and after the
    #: class's decorated methods, which they override. Read from the
    #: class's own namespace: a subclass does not inherit it.
    _grammar_documents: ClassVar[tuple[str | Path, ...]] = ()

    #: Whether the decorated methods (``@element``, ``@abstract``) of
    #: THIS class enter its grammar. ``False`` leaves them out; they are
    #: removed from the class either way. Read from the class's own
    #: namespace: a subclass does not inherit it.
    _decorated_elements: ClassVar[bool] = True

    # -----------------------------------------------------------------------
    # Initialization
    # -----------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Build ``_class_schema``, one layer after the other.

        1. The grammar of the parent builder class. A direct subclass of
           BuilderBase starts from the data-elements declared on
           BuilderBase (``_iter_data_element_methods``).
        2. The class's decorated methods (@element, @abstract; sub-builders
           and data-elements are @element marked in ``_meta``), unless the
           class sets ``_decorated_elements = False``.
        3. The JSON documents named in the class's own
           ``_grammar_documents``, in declared order.

        A later definition of an element or abstract replaces the earlier
        one entirely: nothing of the earlier definition survives. This
        holds for the data-elements too, and for a name declared both by
        a decorator and by a document of the same class: the document
        wins.
        """
        super().__init_subclass__(**kwargs)

        parent_schema = None
        for base in cls.__mro__[1:]:
            if hasattr(base, "_class_schema"):
                parent_schema = base._class_schema
                break
        if parent_schema is not None:
            cls._class_schema = parent_schema.deepcopy()
            # The copy carries the parent's ``_get_schema_info`` cache,
            # resolved against the parent's abstracts; a layer of this
            # class may replace them, so the cache is rebuilt here.
            for node in cls._class_schema:
                node.attr.pop("_cached_info", None)
        else:
            # Abstracts live in a nested Bag rather than at the top level,
            # with no `@` prefix on labels. This keeps element / subbuilder
            # / data_element names cleanly separated from the abstract
            # namespace.
            cls._class_schema = Bag()
            cls._class_schema.set_item("_abstracts", Bag())
            # The data-element stubs are @element on BuilderBase marked
            # with _meta['data_element']; _pop_decorated_methods skips the
            # base, so they enter the grammar here, as its first layer.
            for tag_list, obj, decorator_info in _iter_data_element_methods(BuilderBase):
                for tag in tag_list:
                    cls._class_schema.set_item(
                        tag, None, **_decorated_schema_attrs(obj, decorator_info))
        abstracts_bag = cls._class_schema["_abstracts"]

        # The generator removes the decorated methods from the class, so
        # it is consumed even when they do not enter the grammar.
        use_decorated = cls.__dict__.get("_decorated_elements", True)
        for tag_list, obj, decorator_info in _pop_decorated_methods(cls, BuilderBase):
            if not use_decorated:
                continue
            is_abstract = decorator_info.get("abstract", False)
            target = abstracts_bag if is_abstract else cls._class_schema
            for tag in tag_list:
                target.set_item(tag, None, **_decorated_schema_attrs(obj, decorator_info))

        for path in _grammar_document_paths(cls):
            abstracts, elements = _read_grammar_document(path)
            for tag, attrs in abstracts.items():
                abstracts_bag.set_item(tag, None, **attrs)
            for tag, attrs in elements.items():
                cls._class_schema.set_item(tag, None, **attrs)

        # Validate `inherits_from` references: each name in the
        # comma-separated list must exist among the abstracts. Errors
        # are raised at class definition time so dialect authors see
        # them immediately (no silent fallback at instantiation).
        abstracts_bag = cls._class_schema["_abstracts"]
        known_abstracts = {node.label for node in abstracts_bag}
        for node in cls._class_schema:
            if node.label == "_abstracts":
                continue
            raw = node.get_attr("inherits_from")
            if not raw:
                continue
            for parent in (p.strip() for p in raw.split(",")):
                if not parent:
                    continue
                if parent not in known_abstracts:
                    raise ValueError(
                        f"{cls.__name__}.{node.label}: "
                        f"inherits_from={parent!r} not found among abstracts; "
                        f"available: {sorted(known_abstracts)}"
                    )

        # Abstract inheritance, as genro-builders-js ``resolveAbstract``
        # checks it: every parent of an abstract exists and no chain
        # comes back to itself.
        abstract_parents = {
            node.label: [p.strip() for p in (node.get_attr("inherits_from") or "").split(",")
                         if p.strip()]
            for node in abstracts_bag
        }
        for label, parents in abstract_parents.items():
            for parent in parents:
                if parent not in known_abstracts:
                    raise ValueError(
                        f"{cls.__name__}._abstracts.{label}: "
                        f"inherits_from={parent!r} not found among abstracts; "
                        f"available: {sorted(known_abstracts)}"
                    )
        acyclic: set[str] = set()

        def _check_chain(label: str, trail: tuple[str, ...]) -> None:
            if label in trail:
                cycle = " -> ".join((*trail, label))
                raise ValueError(f"{cls.__name__}: abstract inheritance cycle: {cycle}")
            if label in acyclic:
                return
            for parent in abstract_parents[label]:
                _check_chain(parent, (*trail, label))
            acyclic.add(label)

        for label in abstract_parents:
            _check_chain(label, ())

        # Validate sub_tags specs eagerly: a grammar typo must surface at
        # class definition, not at the first lazy _get_schema_info. The
        # parse is discarded here; the cached compile happens lazily.
        for node in cls._class_schema:
            spec = node.get_attr("sub_tags")
            if spec:
                try:
                    _parse_sub_tags_spec(spec)
                except ValueError as exc:
                    raise ValueError(
                        f"{cls.__name__}.{node.label}: {exc}"
                    ) from None

        _check_custom_type_names(cls._class_schema)
        cls._schema_tag_names = {}
        for node in cls._class_schema.nodes:
            label = node.label
            if label.startswith("_"):
                continue
            key = label.lower()
            if key in cls._schema_tag_names:
                existing = cls._schema_tag_names[key]
                raise ValueError(
                    f"Duplicate (case-insensitive) tag in {cls.__name__}: "
                    f"{existing!r} and {label!r} both lowercase to {key!r}"
                )
            cls._schema_tag_names[key] = label

        # @container dispatch map (legacy gnrwebstruct parity): dispatch
        # name = explicit ``@container('alias')`` if given, else attr name
        # with the prefix-before-first-underscore stripped, else attr name;
        # stored lowercase; same dispatch name on a different attr name
        # collides. The scan walks the WHOLE reverse MRO (the class's own
        # dict last, so it wins): containers live in plain mixins too
        # (DemoContainers), which have no __init_subclass__ of their
        # own. Containers are skipped by _pop_decorated_methods, so they
        # stay callable on the class.
        merged: dict[str, str] = {}
        for klass in reversed(cls.__mro__):
            parent_map = klass.__dict__.get("_containers")
            if parent_map:
                merged.update(parent_map)
            for attr_name, obj in klass.__dict__.items():
                decorator = getattr(obj, "_decorator", None)
                if decorator is None or not decorator.get("container"):
                    continue
                explicit = decorator.get("name")
                dispatch_name = explicit if explicit is not None else attr_name
                key = dispatch_name.lower()
                existing = merged.get(key)
                if existing is not None and existing != attr_name:
                    raise ValueError(
                        f"@container '{dispatch_name}' is already tied to "
                        f"implementation method '{existing}' (cannot rebind "
                        f"to '{attr_name}')"
                    )
                merged[key] = attr_name
        cls._containers = merged

        name = cls.__dict__.get("_name")
        if name is not None:
            if not isinstance(name, str):
                raise TypeError(
                    f"{cls.__name__}._name must be str, got {type(name).__name__}"
                )
            existing_builder = BuilderBase._registry.get(name)
            if existing_builder is not None and existing_builder is not cls:
                raise ValueError(
                    f"Builder name {name!r} already registered to "
                    f"{existing_builder.__name__}; cannot register {cls.__name__}"
                )
            BuilderBase._registry[name] = cls

    @classmethod
    def get_builder_class(cls, name: str) -> type:
        """Look up a registered Builder class by its canonical ``_name``.

        If ``name`` is not in the registry, attempts a lazy import of
        ``genro_builders.contrib.<name>`` to give the dialect a chance
        to register itself via ``__init_subclass__``. This keeps the
        ``_meta['subbuilder']`` references decoupled from import
        order: mutual references (HTML <-> SVG) need not eagerly
        import each other.

        Raises:
            LookupError: if no builder is registered under ``name``
                after the auto-import attempt.
        """
        if name not in BuilderBase._registry:
            with contextlib.suppress(ImportError):
                __import__(f"genro_builders.contrib.{name}")
        try:
            return BuilderBase._registry[name]
        except KeyError:
            raise LookupError(f"No builder registered with name {name!r}") from None

    @classmethod
    def to_grammar(cls, path: str | Path) -> None:
        """Serialize to v1.1 JSON, or v1.2 when named custom types are used.

        The output is a language-neutral document that describes the
        builder's grammar (two sections: abstracts and elements;
        sub-builders and data-elements are elements marked in ``_meta``)
        so that a consumer in another environment can reconstruct an
        equivalent schema.

        Format specification: see ``GRAMMAR_FORMAT.md`` co-located
        with this module.

        Args:
            path: Destination file path. Recommended basename matches
                the grammar name (e.g. ``html.json``).
        """
        document = _class_schema_to_grammar_document(cls)
        Path(path).write_text(
            json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )

    def __init__(self, name: str | None = None) -> None:
        """Initialize the builder: identity, grammar state, source wrapper.

        ``name`` is the builder's identity — a label, not an address: the
        datastore is flat, so the name is no longer a path segment.
        Omitted, it defaults to the dialect typology (``_name``, e.g.
        ``"html"``).

        Renderers are exposed as ``renderer_<mode>`` properties on the
        builder class. The base class declares ``renderer_xml`` so the
        ``xml`` mode is always available; concrete dialects declare
        their own (``renderer_html`` on ``HtmlBuilder`` etc.).

        The source lives under the structural ``SOURCE_ROOT`` segment of
        a wrapper root (tree-not-forest guarantee, never an address):
        ``self.source`` is the payload the ``main`` recipe populates,
        ``_sourceroot`` the wrapper that carries it. Both are instances of
        :attr:`_source_class`. The datastore has the same shape:
        ``self.data`` is the content node ``DATA_ROOT`` of the private
        wrapper ``_dataroot``.
        """
        self.name: str | None = name or type(self)._name
        self._schema = type(self)._class_schema
        self._schema_tag_names = type(self)._schema_tag_names
        self._sourceroot: SourceBag = self._source_class(builder=self)
        self._sourceroot[SOURCE_ROOT] = self._source_class(builder=self)
        self.source: SourceBag = self._sourceroot[SOURCE_ROOT]
        self._sourceroot.set_backref()
        self._default_targets: dict[str, Any] = {}
        # Last walk result per render mode, kept instead of dropped: the
        # materialized form of the source, whatever the mode's renderer
        # emits (text chunks, dicts, objects). A re-render replaces the
        # entry.
        self.materialized: dict[str, Any] = {}
        # The datastore: ONE flat Bag per document, owned by the builder.
        # ``setup`` seeds it, pointers read it, ``node.data`` reaches it
        # from any node through the ancestor walk. It is the content node
        # ``DATA_ROOT`` of the private wrapper ``_dataroot``, as the source
        # is under ``_sourceroot``; the content node is never replaced.
        self._dataroot: Bag = Bag()
        self._dataroot[DATA_ROOT] = Bag()
        self.data: Bag = self._dataroot[DATA_ROOT]
        self._dataroot.set_backref()
        # data-element logic sources, resolved lazily by ``data_logic``.
        self._data_logic: list[Any] | None = None
        # Sub-builder instances, one per dialect name or grammar class
        # (see get_subbuilder).
        self._subbuilders: dict[str | type, Any] = {}
        # Per-document DOM-id serial (see ``target_id``): the root builder
        # is the identity authority, sub-builder subtrees draw from the
        # host's counter through ``node.root_builder``.
        self._target_serial: int = 0

    @property
    def renderer_xml(self) -> XmlRenderer:
        """Fresh ``XmlRenderer`` instance bound to this builder.

        Each access returns a new instance: the renderer is meant to be
        ephemeral, used for a single ``render`` call and discarded.
        Inherited by every concrete dialect so ``xml`` is always
        available as a render mode.
        """
        return XmlRenderer(builder=self)

    @property
    def renderer_yaml(self) -> YamlRenderer:
        """Fresh ``YamlRenderer`` instance bound to this builder.

        Inherited by every dialect so ``yaml`` is always available as a
        render mode. PyYAML is an optional dependency (extra ``[yaml]``):
        the renderer raises a clear error at render time if it is absent.
        """
        return YamlRenderer(builder=self)

    def new_root(self) -> SourceBag:
        """Return a fresh, throw-away Source driven by this builder.

        The Source is an instance of :attr:`_source_class`.

        The returned source carries this builder (so the grammar API
        works: ``root.div(...)`` etc.) and has backref enabled (so
        ``parent_node`` is usable). It cannot ``create()`` or
        ``render()``: it is a subtree, not a document.

        Typical use: pre-build a subtree offline, then attach it as the
        value of some node in a document's source; the next render walks
        it and resolves its pointers. The throw-away root itself is not
        retained by anything.
        """
        root = self._source_class(builder=self)
        root.set_backref()
        return root

    def _expansion_root(self, datapath: str | None = None) -> SourceBag:
        """Fresh throw-away root for a component expansion (CMP.2).

        Same structural shape as the document source — a payload under
        ``SOURCE_ROOT`` inside a wrapper: the wrapper is the transparent
        throw-away container the design names (discarded with the whole
        expansion, never an address), and the expansion nodes get real
        fullpaths (pretty depth, future path arithmetic). Unlike
        :meth:`new_root`, the result is not meant to be attached
        anywhere: it is built, rendered and dropped.

        ``datapath`` is the expansion's data anchor (the component's
        ``store``, CMP.3): stamped on the structural node — the wrapper
        is the machinery's own object — so the body's relative pointers
        (``^.company``) find it through the ordinary ancestor climb.
        """
        wrapper = self._source_class(builder=self)
        attrs = {"datapath": datapath} if datapath else {}
        wrapper.set_item(
            SOURCE_ROOT, self._source_class(builder=self),
            _attributes=attrs,
        )
        wrapper.set_backref()
        return wrapper[SOURCE_ROOT]

    def get_subbuilder(self, name: str | type) -> Any:
        """Return THE sub-builder instance for ``name``, cached per host.

        ``name`` is a registry name (looked up via
        :meth:`get_builder_class`) or a grammar class (a mixin of
        ``@element`` methods, ``Html5Elements`` style, resolved from a
        ``kwarg:attr`` subbuilder reference): the builder class is then
        fabricated by :meth:`_builder_class_from_grammar`. Either way the
        instance is memoised per host (the same pattern as the renderer
        cache: one instance per host per dialect, so every ``<svg>``
        subtree of the document shares one ``SvgBuilder`` and the
        renderer cache keyed by ``id(builder)`` serves them all with a
        single sub-renderer). Used when a ``_meta['subbuilder']`` element
        switches the active dialect mid-document (e.g. ``body.svg(...)``
        inside HTML). The host's DATASTORE is passed on so the
        sub-builder resolves pointers against the same document data; it
        cascades to nested sub-builders. The wrapper ``_dataroot`` is
        passed on with it, so a subscriber on the host's wrapper sees the
        sub-builder's writes.
        """
        subbuilder = self._subbuilders.get(name)
        if subbuilder is None:
            if isinstance(name, type):
                builder_class = self._builder_class_from_grammar(name)
            else:
                builder_class = type(self).get_builder_class(name)
            subbuilder = builder_class()
            self._subbuilders[name] = subbuilder
        subbuilder._dataroot = self._dataroot
        subbuilder.data = self.data
        return subbuilder

    def _builder_class_from_grammar(self, grammar: type) -> type:
        """Return the builder class for a grammar mixin, fabricated once.

        A class that is already a ``BuilderBase`` subclass is used as-is.
        Otherwise the class is composed exactly like a hand-written
        dialect — ``(grammar, BuilderBase)``, the ``HtmlBuilder``
        shape — so ``__init_subclass__`` collects the mixin's
        ``@element`` methods through the MRO; plain inheritance between
        grammar classes composes grammars the same way. The result is
        cached in :attr:`_grammar_builders` per grammar class. A grammar
        contributing no elements of its own (the schema holds only the
        data-elements of BuilderBase) is an authoring error and raises.
        """
        if issubclass(grammar, BuilderBase):
            return grammar
        fabricated = BuilderBase._grammar_builders.get(grammar)
        if fabricated is None:
            fabricated = type(BuilderBase)(
                f"{grammar.__name__}Builder", (grammar, BuilderBase), {},
            )
            declared = [
                node.label for node in fabricated._class_schema
                if not node.label.startswith("_")
                and not (node.get_attr("_meta") or {}).get("data_element")
            ]
            if not declared:
                raise ValueError(
                    f"{grammar.__name__} declares no grammar elements: "
                    "it cannot govern a subbuilder subtree",
                )
            BuilderBase._grammar_builders[grammar] = fabricated
        return fabricated

    def main(self, root: SourceBag) -> None:
        """Build the document into ``root``. Override on a page subclass.

        The base raises: a bare builder is grammar, not a renderable page.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no 'main': it is grammar, not a "
            "renderable page",
        )

    def setup(self, data: Any) -> None:
        """Override point: populate the datastore.

        Receives the datastore WHOLE — one flat Bag per document, no
        per-builder segment. Default no-op — a page with pointers
        overrides it to seed the values its ``main`` reads. Called by
        :meth:`create` before ``main``.
        """

    def create(self) -> None:
        """Build the document, then compute the logic.

        Sequence: ``setup(self.data)`` seeds the data, ``main(self.source)``
        builds the document, then EVERY data-element runs, once, in
        document order (the ``deep=True`` query walks the tree top to
        bottom): a ``dataSetter`` seeds its value, a ``dataFormula`` writes
        its result, a ``dataController`` fires its side effects.

        Compute-then-render is the whole model: when ``render()`` runs, the
        datastore is already complete, so a node may read a value a
        data-element writes further DOWN the document. It is a single pass
        and there is no recompute — a formula reading a value that another
        formula writes AFTER it sees the earlier value. Ordering the
        calculations is the author's job, exactly as in a script.
        """
        self.setup(self.data)
        self.main(self.source)
        self.compute_logic(
            self.source.query(
                what="#n", deep=True,
                condition=lambda n: bool(n._get_meta("data_element")),
            )
        )

    def node_by_id(self, node_id: str) -> Any:
        """Return the source node carrying ``node_id`` in this builder.

        Walk-based lookup over this builder's source tree (the node_id
        namespace is per-builder). Raises ``KeyError`` if no node carries
        the requested id.
        """
        node = self.source.get_node_by_attr("node_id", node_id)
        if node is None:
            raise KeyError(node_id)
        return node

    def target_id(self, node: Any) -> str | None:
        """Per-document serial naming a source node in the output.

        Emitted as the element's ``id`` under ``include_datapath``.
        Assigned on first emission from the root builder's counter
        (``n1``, ``n2``, ... — render order, so deterministic for a given
        program), stored on the node, never recomputed: it is bound to
        the OBJECT, not to its position, so no structural mutation can
        stale it.

        Expansion nodes get none: they live in a throw-away wrapper, not
        in the document's own ``_sourceroot``, and they reincarnate at
        every render — no stable identity to name.
        """
        existing = getattr(node, "_target_id", None)
        if existing is not None:
            return existing
        if node.parent_bag.root is not node._resolve_builder()._sourceroot:
            return None
        root = node.root_builder
        root._target_serial += 1
        node._target_id = f"n{root._target_serial}"
        return node._target_id

    # ------------------------------------------------------------------
    # Data-element logic
    # ------------------------------------------------------------------

    def compute_logic(self, nodes: Iterable[Any]) -> None:
        """Execute a list of data-element nodes through ``_compute_node``."""
        for node in nodes:
            self._compute_node(node)

    def _compute_node(self, node: Any) -> None:
        """Execute a single data-element node according to its kind.

        - ``dataSetter`` seeds the data: write its value at destination;
        - ``dataFormula`` is pure: ``func(**bindings)`` -> destination;
        - ``dataController`` has side effects: ``func(node, **bindings)``.
        """
        match node.node_tag:
            case "dataSetter":
                # The setter's schema fields and the framework markers
                # stay on the source node; only user attributes ride
                # onto the datum being seeded.
                attrs = {k: v for k, v in node.attr.items()
                         if k not in ("destination", "value")
                         and k not in self._meta_attrs}
                node.set_relative_data(
                    node.attr["destination"], node.attr["value"],
                    attributes=attrs or None,
                )
            case "dataFormula":
                func = self._resolve_logic_func(node.attr["func"])
                node.set_relative_data(
                    node.attr["destination"], func(**self._bindings(node)),
                )
            case "dataController":
                func = self._resolve_logic_func(node.attr["func"])
                func(node, **self._bindings(node))

    def _bindings(self, node: Any) -> dict[str, Any]:
        """Resolve a data-element node's bindings via ``runtime_values``.

        ``runtime_values`` resolves ``^``/``=`` and ``${}``; here we strip
        the element's own schema fields (``destination`` / ``func`` /
        ``value``), so what remains are the func bindings.
        """
        fields = set(self._get_schema_info(node.node_tag).get(
            "call_args_validations") or {})
        _, resolved = self.runtime_values(node)
        return {k: v for k, v in resolved.items() if k not in fields}

    @property
    def data_logic(self) -> list[Any]:
        """Sources searched (left-to-right) to resolve a data-element func.

        Default is ``[self]`` (the builder owns its logic). Subclasses
        override ``_build_data_logic`` to add more sources.
        """
        if self._data_logic is None:
            built = self._build_data_logic()
            self._data_logic = (
                list(built) if isinstance(built, (list, tuple)) else [built]
            )
        return self._data_logic

    def _build_data_logic(self) -> Any:
        """Override point: return the data_logic source(s). Default ``self``."""
        return self

    def _resolve_logic_func(self, name: str) -> Any:
        """Resolve ``name`` to a ``@staticmethod`` over ``data_logic`` sources.

        Left-to-right, first-wins. A source owning the name but NOT as a
        staticmethod raises TypeError; miss on every source raises
        AttributeError.
        """
        for source in self.data_logic:
            try:
                attr = inspect.getattr_static(source, name)
            except AttributeError:
                continue
            if not isinstance(attr, staticmethod):
                raise TypeError(
                    f"data-element func {name!r} on {type(source).__name__} "
                    "must be a @staticmethod",
                )
            return getattr(source, name)
        sources = ", ".join(type(s).__name__ for s in self.data_logic)
        raise AttributeError(
            f"data-element func {name!r} not found on any data_logic "
            f"source ({sources})",
        )

    def runtime_values(self, node: Any) -> tuple[Any, dict[str, Any]]:
        """Resolve the pointers/templates/resolvers carried by ``node``.

        Returns ``(runtime_value, runtime_attrs)``. Resolution lives on
        the builder, which owns the datastore; ``node`` is just the subject
        whose pointers are resolved. ``^``/``=`` strings are read from
        ``self.data`` at the node's absolute path; ``${name}`` templates
        expand only inside attributes, against the resolved attrs. A preceding
        backslash protects a token and is removed. Node values are not templates.
        Data elements carry code, not presentation: their attributes are never
        templates (a controller script uses ``${...}`` as JavaScript). A name
        that is not a resolved attribute raises ``ValueError``.

        A ``BagResolver`` found as the node value or in an attribute is
        CALLED, and its result is the resolved datum: a resolver supplies
        a value in place, so the recipe declares it where the value lives
        instead of pairing a datastore entry with a pointer. It needs no
        node of its own — caching and TTL live in the resolver.

        ``^`` and ``=`` resolve identically here: the difference is an
        author's declaration of INTENT (``^`` "this is meant to follow the
        datum"), which a reactive engine would act on. A static render
        reads both, once.

        An attribute referenced by a ``${...}`` template of the same node
        is a template input: once expanded it has been consumed, and it is
        dropped from the returned attrs — no renderer emits it. The name
        is free (``w``, ``foo``); it is the usage, visible in the recipe,
        that marks it. Canonical idiom for "computed datum + authored
        unit": ``div(w="^mywidth", width="${w}px")``. An attribute meant
        to be BOTH emitted and reused goes through a template itself:
        ``t="hello", title="${t}", aria_label="${t} world"``.
        """
        node.builder._validate_custom_types(node)
        is_data_element = bool(node._get_meta("data_element"))
        resolved: dict[Any, Any] = {}
        carried: dict[str, Any] = {}
        for k, v in node.runtime_to_evaluate().items():
            if isinstance(v, BagResolver):
                # A resolver SUPPLIES the value, wherever it sits: as the
                # node value (key ``None``) or in an attribute. Calling it
                # IS the resolution — caching and TTL live in the resolver,
                # which works with no node of its own.
                resolved[k] = v()
                continue
            ptype = node.pointer_type(v)
            if not ptype:
                resolved[k] = v
                continue
            abs_path = node.abs_datapath(v)
            value = self.data.get_item(abs_path)
            # The datum knows how to present itself. Presentation only:
            # never for a data-element's bindings (formulas want the raw
            # datum) and never for ``?attr`` reads (raw by definition).
            # - ``mask`` wraps the value (legacy gnrformatter vocabulary,
            #   ``%s`` = the value);
            # - ``_wdg`` (value reads only) is a dict of attributes the
            #   datum carries onto its reader — the exception that
            #   travels with the data (e.g. an alarm color).
            if not is_data_element and "?" not in abs_path:
                data_node = self.data.get_node(abs_path)
                if data_node is not None:
                    value = self._present_value(data_node, value)
                    if k is None:
                        wdg = data_node.attr.get("_wdg")
                        if wdg:
                            carried.update(wdg)
            resolved[k] = value

        consumed: set[str] = set()

        def _expand(s: str) -> str:
            def repl(m: re.Match[str]) -> str:
                if m.group(1):
                    return m.group(0)[1:]
                name = m.group(2)
                if name not in resolved:
                    raise ValueError(f"Unknown template parameter '{name}'")
                consumed.add(name)
                val = resolved[name]
                return "" if val is None else str(val)
            return _TEMPLATE_RE.sub(repl, s)

        for k, v in resolved.items():
            if is_data_element or k is None:
                continue
            if isinstance(v, str) and "${" in v:
                resolved[k] = _expand(v)

        runtime_value: Any = resolved.pop(None)
        # Template inputs were consumed by the expansion above; they are
        # not part of the node's runtime attrs.
        resolved = {k: v for k, v in resolved.items() if k not in consumed}
        # ``_wdg`` attributes carried by the datum override the recipe's:
        # what travels with the data is the exception, and the exception
        # wins over the static default.
        resolved.update(carried)
        return runtime_value, resolved

    def get_renderer(self, mode: str | None = None) -> Any:
        """Return the renderer for ``mode`` (default: the dialect's own).

        The ``renderer_<mode>`` properties are the single declaration of
        which renderer serves which mode; this resolves one of them
        without going through a render.
        """
        mode = mode or self._default_render_mode
        return getattr(type(self), f"renderer_{mode}").__get__(self, type(self))

    def materialize(self, mode: str | None = None, **opts: Any) -> Any:
        """Walk the source and keep the result in ``materialized[mode]``.

        The walk's product — whatever the mode's renderer emits: text
        chunks, dicts, live objects — is stored under the mode and also
        returned. It does not validate and it does not deliver:
        :meth:`render` composes this with ``finalize``, and calling the
        two separately is what lets one walk feed several deliveries.
        """
        mode = mode or self._default_render_mode
        renderer = self.get_renderer(mode)
        self.materialized[mode] = renderer.render_children(
            renderer.preprocess(self.source), **opts,
        )
        return self.materialized[mode]

    def validate_source(self) -> list[tuple[str, list[str]]]:
        """Report the source nodes whose minimum child cardinality is unmet.

        Returns ``(fullpath, [missing tags])`` per incomplete node, empty
        when the document is complete. The maximum is enforced at
        insertion; the minimum only makes sense once the author declares
        the document finished, which is why this is called, never implied
        by a render.

        It walks the SOURCE, so a component is the single node the author
        wrote — the expansion it produces is a render-time fact and is not
        inspected here. For XSD dialects this is the structural first net,
        not a replacement for full XSD validation downstream.

        Each node is checked against its OWN builder's grammar, so a
        sub-builder subtree is validated by the dialect that authored it.
        Nodes the containment grammar ignores (data-elements, sub-builder
        envelopes, components) are skipped, per
        :meth:`require_sub_tag_validation`.
        """
        problems = []
        for node in self.source.traverse():
            builder = node.builder
            builder._validate_custom_types(node)
            if not builder.require_sub_tag_validation(node):
                continue
            missing = builder._validate_sub_tags(
                node, builder._get_schema_info(node.node_tag),
            )
            if missing:
                problems.append((node.fullpath, missing))
        return problems

    def render(
        self, mode: str | None = None, target: Any = None, **opts: Any,
    ) -> Any:
        """Render the built source via ``renderer_<mode>``.

        The builder renders itself: grammar, data and render in one object.
        ``mode`` defaults to the dialect's ``_default_render_mode``;
        ``target`` follows :meth:`_get_target` (``False`` returns the
        string, a falsy value falls back to a registered target, a truthy
        value is used directly).

        Two steps, one gesture: :meth:`materialize` walks,
        ``finalize`` delivers. Rendering does not validate — call
        :meth:`validate_source` when the document must be checked.
        """
        mode = mode or self._default_render_mode
        renderer = self.get_renderer(mode)
        effective_target = self._get_target(target, renderer)
        if isinstance(effective_target, TargetWrapper):
            # The destination dictates the form of every delivery (e.g. a
            # patch consumer needs the DOM ids): its walk options are the
            # base, the call's own opts win.
            opts = {**effective_target.render_opts, **opts}
        result = self.materialize(mode, **opts)
        return renderer.finalize(result, effective_target, **opts)

    def _present_value(self, data_node: Any, value: Any) -> Any:
        """Apply the datum's presentation mask.

        The datum knows how to present itself: ``mask`` is a %-format
        whose single argument is the value — ``%s`` wraps (``"%s°"``),
        a numeric directive fixes the shape (``"%.2f"``, ``"€ %.2f"``;
        legacy gnrformatter vocabulary). Bags and missing values pass
        raw; a mask/value mismatch raises — the datum declared a
        presentation it cannot honour.
        """
        mask = data_node.attr.get("mask")
        if mask and value is not None and not isinstance(value, Bag):
            return str(mask) % value
        return value

    def _get_target(self, target: Any, renderer: Any) -> Any:
        """Resolve the render target for a render call.

        - ``False`` → return-as-value: ``None`` for a string renderer, an
          error for an object renderer (no string to return);
        - any other falsy value → the target registered for the renderer's
          mode via :meth:`set_render_target` (``None`` if none);
        - a truthy value → used as-is.
        """
        if target is False:
            if renderer.render_type != "string":
                raise TypeError(
                    f"target=False (return-as-value) is not valid for an "
                    f"object renderer ({type(renderer).__name__})",
                )
            return None
        return target or self._default_targets.get(renderer.mode)

    def set_render_target(self, target: Any, mode: str | None = None) -> None:
        """Register a render target, by default for the dialect's own mode.

        ``mode`` defaults to the dialect's ``_default_render_mode`` (e.g.
        ``"html"`` for HtmlBuilder), so the common case is just
        ``set_render_target("output.html")``. Pass ``mode`` to register a
        target for a different render mode (e.g. an ``xml`` view). A target
        passed explicitly to :meth:`render` still wins over the registered
        one.
        """
        self._default_targets[mode or self._default_render_mode] = target

    @property
    def rendered_target(self) -> str:
        """Read back the file written by the last render to the default mode.

        Returns the text content of the file registered as the target for
        the dialect's ``_default_render_mode`` (a string renderer writes
        its output there). Use after :meth:`render` to inspect what was
        produced without re-rendering.

        Raises:
            KeyError: no target registered for the default mode.
            TypeError: the registered target is not a file path (e.g. a
                writable or a callable) — there is no file to read back.
        """
        mode = self._default_render_mode
        target = self._default_targets.get(mode)
        if target is None:
            raise KeyError(
                f"no render target registered for mode {mode!r}; "
                "call set_render_target first",
            )
        if not isinstance(target, (str, Path)):
            raise TypeError(
                f"render target for mode {mode!r} is not a file path; "
                "there is no file to read back",
            )
        return Path(target).read_text(encoding="utf-8")

    def include_components(self, *mixins: type) -> None:
        """Enrich THIS instance's grammar with the @component methods
        of the given mixin classes.

        Per-instance: the class schema (and its tag-name map) is copied
        on first use, so other instances of the same builder are left
        untouched. Each component method is bound onto the instance
        (it is already callable — components are never delattr'd) and
        registered in the schema marked ``_meta['component']``, so the
        node API (``node.<name>(...)``) finds it. A component overrides
        a same-named plain element (last-wins, like data-elements).
        """
        if self._schema is type(self)._class_schema:
            self._schema = self._schema.deepcopy()
            self._schema_tag_names = dict(self._schema_tag_names)
        for mixin in mixins:
            for name, obj in vars(mixin).items():
                decorator = getattr(obj, "_decorator", None)
                if not decorator:
                    continue
                if not (decorator.get("_meta") or {}).get("component"):
                    continue
                setattr(self, name, obj.__get__(self))
                self._schema.set_item(
                    name, None,
                    sub_tags=decorator.get("sub_tags", ""),
                    parent_tags=decorator.get("parent_tags"),
                    inherits_from=decorator.get("inherits_from", ""),
                    _meta=decorator.get("_meta"),
                    documentation=obj.__doc__,
                    call_args_validations=_extract_signature_info(obj)[0],
                )
                self._schema_tag_names[name.lower()] = name

    # -----------------------------------------------------------------------
    # Data-elements (core, every dialect inherits them). Plain @element marked
    # ``_meta['data_element']``: bodies ignored (like every @element), the
    # first layer of every grammar built by __init_subclass__ via
    # _iter_data_element_methods, and dispatched through the same
    # _command_on_node as any element. A subclass may redefine them.
    # The signature carries the kind's fields (destination/value/func); every
    # other kwarg is a func binding. There is no flag to request execution:
    # all three run at ``create()``, in document order.
    # -----------------------------------------------------------------------

    @element(_meta={"data_element": True})
    def dataSetter(self, destination: str, value: Any, **attr: Any): ...

    @element(_meta={"data_element": True})
    def dataFormula(
        self, destination: str, func: str | Callable, **kwargs,
    ): ...

    @element(_meta={"data_element": True})
    def dataController(self, func: str | Callable, **kwargs): ...

    #: Default rendering mode used when ``render(mode=None)`` is called.
    #: Concrete dialects override this (e.g. ``"html"`` for HtmlBuilder).
    _default_render_mode: str = "xml"

    #: Structural meta-attributes carried by nodes of this grammar:
    #: identity, anchors and the datapath root — not domain attributes.
    #: ``runtime_values`` drops them from the actualized attribute view,
    #: so they never reach a renderer or a data-element binding; their
    #: readers (``node_by_id``, ``abs_datapath``) take them straight from
    #: ``node.attr``. ``datapath`` is binding state (the relative-pointer
    #: root), not markup: it is read by ``abs_datapath`` along the
    #: ancestor chain, never emitted. A dialect that introduces a new
    #: node-meta extends this set, e.g.
    #: ``_meta_attrs = BuilderBase._meta_attrs | {"_my_marker"}``.
    #: ``ns`` is the namespace prefix: the renderer consumes it to compose
    #: ``<ns>:<tag>`` (in ``_handle_meta``), so it is grammar meta, never
    #: an emitted XML attribute.
    _meta_attrs: frozenset[str] = frozenset(
        {"node_id", "_meta", "_anchor", "datapath", "ns"},
    )

    #: Retained attribute FAMILIES (name prefixes): declared on the
    #: node, readable by whoever resolves the node (a validation engine,
    #: a consumer of the source), but NEVER emitted by a renderer — they are
    #: server-side contract, not markup. Unlike ``_meta_attrs`` (exact
    #: names, dropped before resolution) a retained family stays in the
    #: actualized view and is filtered at emission. ``validate_`` is
    #: the legacy validation vocabulary; ``dtype`` is the declared data
    #: type a mutation resolves on the node (TYTX) — semantics live in
    #: the application layer, the grammar only guarantees retention.
    _retained_attr_prefixes: tuple[str, ...] = ("validate_", "dtype")
