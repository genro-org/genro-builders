# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Builder-aware Bag and BagNode — level 1 of the bag/node layering.

``SourceBag`` and ``SourceBagNode`` are obtained by combining ``Bag``
with ``_SourceBagMixin`` and ``BagNode`` with ``_SourceBagNodeMixin``.
The grammar-aware logic lives in the mixins; the base classes from
``genro-bag`` stay untouched.

Every node carries the ``_builder`` slot — the active dialect for that
node, set at attach time — and nothing else: the datastore is not a node
slot, a node reaches it through its builder (:attr:`data`), so the node
stays light. Immutability of the slot is a convention, not enforced.

This module defines the bag/node pair (``SourceBag`` /
``SourceBagNode``): a Bag/BagNode carrying the active builder plus
grammar-aware attribute resolution. The builder populates one as
``self.source``.
"""
from __future__ import annotations

import keyword
import warnings
from typing import Any

from genro_bag import Bag, BagNode
from genro_tytx import get_subtype_dict, set_subtype_dict

from .pointers import pointer_transform


def _schema_tag(builder: Any, name: str) -> str | None:
    """Resolve ``name`` to a schema tag, honoring the dialect prefix.

    Direct lookup first; when it misses, ``<dialect>_<tag>`` strips the
    active dialect's prefix — the same escape the attributes use
    (``html_type`` -> ``type``), here for tags shadowed by the node/bag
    API (``html_label`` -> ``label``, since ``label`` is BagNode API).
    """
    lookup = name.lower()
    tag = builder._schema_tag_names.get(lookup)
    if tag is not None:
        return tag
    prefix = f"{builder._name}_"
    if lookup.startswith(prefix):
        return builder._schema_tag_names.get(lookup[len(prefix):])
    return None


def _dispatch_container(builder: Any, target: Any, name: str) -> Any | None:
    """Resolve ``name`` as a ``@container`` on ``builder``.

    Returns a callable bound to ``target`` (bag or node) when the name
    matches a registered container on the builder; ``None`` if no
    match (caller falls through to whatever else it wants to try). The
    container runs with ``self`` = the builder and ``target`` as its
    first positional (the node it was invoked from).
    """
    if builder is None:
        return None
    method_name = builder._containers.get(name.lower())
    if method_name is None:
        return None
    bound = getattr(builder, method_name)
    return lambda *args, **kwargs: bound(target, *args, **kwargs)


class _SourceBagNodeMixin:
    """Builder-aware logic for nodes: schema dispatch via __getattr__.

    The actual ``_builder`` slot is declared on the final
    ``SourceBagNode`` class (BagNode itself uses __slots__, so the slot
    must live on the concrete class to avoid a layout conflict).
    """

    __slots__ = ()

    def _resolve_builder(self) -> Any:
        """Return the active builder, falling back to the parent bag.

        Nodes are not always attached with their slots populated (e.g.
        when created via plain ``Bag.set_item``). The slot acts as a
        cache; if empty, look it up on the containing bag.
        """
        try:
            value = object.__getattribute__(self, "_builder")
        except AttributeError:
            value = None
        if value is not None:
            return value
        parent = self.parent_bag
        return getattr(parent, "_builder", None) if parent is not None else None

    @property
    def builder(self) -> Any:
        """Active builder for this node, resolved via slot + ancestor walk.

        Public façade of ``_resolve_builder``: returns the node's own
        ``_builder`` slot if set, otherwise the closest ancestor's. The
        renderer-side chain relies on this to dispatch a node to the
        renderer of its owning builder during the walk.
        """
        return self._resolve_builder()

    def _get_meta(self, keys: str) -> Any:
        """Read schema ``_meta`` values carried by this node.

        The element's ``_meta`` dict (declared on the grammar, copied onto
        the node at creation) holds framework instructions for renderers and
        compilers: ``subbuilder``, ``data_element``, ``render_tag``,
        ``render_attributes``, ``compile_*`` … This is the single accessor.

        - one key (``'render_tag'``) → its value, or ``None``;
        - comma-separated keys (``'render_tag,render_attributes'``) → a list
          of values in order, ``None`` where a key is absent.
        """
        meta = self.attr.get("_meta") or {}
        names = [k.strip() for k in keys.split(",")]
        if len(names) == 1:
            return meta.get(names[0])
        return [meta.get(n) for n in names]

    @property
    def data(self) -> Any:
        """The document's datastore, reached through the owning builder.

        Same name as ``builder.data`` and the same object: one Bag per
        document, whatever level you read it from. Works on a DETACHED
        tree too (a component expansion), because the builder is resolved
        by the ancestor walk, not by the tree's root — an expansion node
        reads and writes the SAME datastore as the document it projects.
        """
        return self._resolve_builder().data

    @property
    def root_builder(self) -> Any:
        """Return the page builder that owns this tree.

        Unlike ``_resolve_builder`` (the local dialect, an ``<svg>``
        subtree resolves to the SVG builder), this is the builder mounted
        on the document — read from the source root via ``Bag.root``. It
        owns the datastore, so data resolution goes through here.
        """
        return self.parent_bag.root._builder

    def _check_unique_id(self, node_id: Any) -> None:
        """Raise ValueError if ``node_id`` is already taken in the
        document. No-op when ``node_id`` is None.

        Called before adding a child, so the candidate id is checked
        against the existing tree only. Uniqueness is guaranteed by the
        ROOT builder: one node_id namespace per document, sub-builder
        subtrees included (the page-level ``node_by_id`` lookup and the
        symbolic pointers cross dialect boundaries, so the practical
        identity space is the document).

        When no root builder is reachable, the check is a no-op.
        """
        if node_id is None:
            return
        parent = self.parent_bag
        builder = getattr(parent.root, "_builder", None) if parent is not None else None
        if builder is None:
            return
        try:
            builder.node_by_id(node_id)
        except KeyError:
            return
        raise ValueError(f"Duplicate node_id '{node_id}'.")

    def pointers(self) -> list[tuple[str, str]]:
        """Return the pointers carried by this node as ``(attrname, pointer)``.

        ``attrname=""`` for a pointer in ``node.value``, otherwise the
        attribute name. A pointer is any string starting with ``^``.
        Walks only this node — does not recurse into children.
        """
        self.builder._validate_custom_types(self)
        result: list[tuple[str, str]] = [
            (attrname, v.split(":", 1)[0])
            for attrname, v in self.attr.items()
            if self.pointer_type(v) == "^"
        ]
        value = self.value
        if self.pointer_type(value) == "^":
            result.append(("", value.split(":", 1)[0]))
        return result

    def pointer_type(self, v: Any) -> str | None:
        """Return ``"^"`` (reactive), ``"="`` (passive) or ``None``."""
        if isinstance(v, str) and v[:1] in ("^", "=") and not v.startswith("=="):
            return v[0]
        return None

    def fixed_attr_items(self) -> Any:
        """Yield ``(name, value)`` for domain attributes, names canonicalized.

        Skips structural meta-attributes and resolves Python-keyword forms
        (``class_`` / legacy ``_class`` -> ``class``).
        """
        meta_attrs = self._resolve_builder()._meta_attrs
        for attrname, v in self.attr.items():
            if attrname in meta_attrs:
                continue
            if attrname.endswith("_") and keyword.iskeyword(attrname[:-1]):
                attrname = attrname[:-1]
            elif attrname.startswith("_") and keyword.iskeyword(attrname[1:]):
                warnings.warn(
                    f"attribute '{attrname}': the leading-underscore form is "
                    f"deprecated, use '{attrname[1:]}_' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
                attrname = attrname[1:]
            yield attrname, v

    def runtime_to_evaluate(self) -> dict[Any, Any]:
        """Attributes to resolve plus the node value under key ``None``."""
        items: dict[Any, Any] = dict(self.fixed_attr_items())
        items[None] = self.value
        return items

    # ------------------------------------------------------------------
    # Path composition (DAT.2)
    # ------------------------------------------------------------------

    def abs_datapath(self, path: str) -> str:
        """Compose the absolute path for ``path`` relative to this node.

        Pure address composition: returns *where* a datum lives as a
        string, never reads the datastore. The store is flat — it belongs
        to the builder itself — so an absolute path carries no leading
        segment. Supported syntactic forms:

            ``field``               — already absolute, returned as is
            ``^...`` / ``=...``     — pointer mark stripped, recurses.
                                       ``abs_datapath`` is neutral wrt
                                       the prefix; the lazy/eager
                                       distinction (``^`` vs ``=``)
                                       lives in ``runtime_values``
                                       and in the pointer-map registry
            ``field?attr``          — ``?attr`` is preserved at the tail
            ``.field`` / ``.x``     — relative: walk ancestors and
                                       chain their ``datapath`` attribute
                                       until the result is absolute;
                                       ``ValueError`` if the chain ends
                                       without an absolute anchor
            ``a.#parent.b``         — ``#parent`` segments cancel the
                                       preceding segment (filesystem
                                       ``..`` equivalent); ``ValueError``
                                       if it has nothing left to cancel
            ``#FORM.x``             — relative to the nearest ancestor
                                       marked with ``formId`` set or
                                       ``form=True``; ``KeyError`` if no
                                       such ancestor
            ``#ANCHOR.x``           — relative to the nearest ancestor
                                       with attr ``_anchor`` present;
                                       ``KeyError`` otherwise
            ``#<node_id>.x``        — relative to the node carrying that
                                       ``node_id`` (any other ``#xxx``
                                       falls in here); ``KeyError`` if
                                       no node carries that id
        """
        raw = path
        if self.pointer_type(path):
            transform = pointer_transform(path)
            path = (transform[0] if transform else path)[1:]

        attr: str | None = None
        if "?" in path:
            path, attr = path.split("?", 1)

        if path.startswith("#"):
            return self._finalize_abs_path(self._resolve_symbolic_datapath(path, raw), attr)

        if path.startswith("."):
            path = self._compose_relative_datapath(path, raw)
        return self._finalize_abs_path(path, attr)

    def _finalize_abs_path(self, path: str, attr: str | None) -> str:
        """Collapse ``path`` into a final absolute datastore path.

        ``#parent`` segments are resolved and ``?attr`` is re-attached at
        the tail when present.
        """
        path = self._collapse_parent_datapath(path, path)
        return f"{path}?{attr}" if attr else path

    def _compose_relative_datapath(self, path: str, raw: str) -> str:
        """Resolve a relative path by walking ancestors.

        Chains ``attr["datapath"]`` of ancestors (starting from this
        node) in front of ``path`` until the result no longer starts
        with ``.``. Stops at the first ancestor whose ``datapath`` is
        absolute. Raises ``ValueError`` if the chain ends while
        ``path`` is still relative.

        A bare ``"."`` denotes the current datapath itself (no child
        segment) — used by ``.?attr`` paths that read an attribute of the
        datapath node. It resolves to the datapath alone, without a dangling
        trailing dot (so ``.?b`` -> ``triangolo?b``, not ``triangolo.?b``).
        """
        # ``current`` typed as Any: the mixin is combined with BagNode
        # at runtime to form SourceBagNode, but pyright analyses the
        # mixin in isolation and can't see the eventual concrete shape.
        current: Any = self
        while current is not None and path.startswith("."):
            dp = current.attr.get("datapath")
            if dp is not None:
                path = dp if path == "." else dp + path
            current = current.parent_node
        if path.startswith("."):
            raise ValueError(f"unresolved relative datapath: {raw!r}")
        return path

    def _collapse_parent_datapath(self, path: str, raw: str) -> str:
        """Collapse ``#parent`` segments in a composed path.

        Path-level rewrite: each ``#parent`` segment cancels the segment
        immediately before it (``a.b.#parent.c`` -> ``a.c``). Raises
        ``ValueError`` when ``#parent`` has no segment left to cancel,
        rather than silently dropping it.
        """
        out: list[str] = []
        for segment in path.split("."):
            if segment == "#parent":
                if not out:
                    raise ValueError(
                        f"#parent has no segment to cancel: {raw!r}"
                    )
                out.pop()
            else:
                out.append(segment)
        return ".".join(out)

    def _resolve_symbolic_datapath(self, path: str, raw: str) -> str:
        """Resolve a ``#SYMBOL[.relpath]`` path.

        Dispatch (path starts with ``#``):
            ``#FORM``       — nearest ancestor with attr ``formId`` set
                              OR ``form=True``;
            ``#ANCHOR``     — nearest ancestor with attr ``_anchor``
                              present (any value);
            ``#<id>``       — node carrying that ``node_id`` (any other
                              ``#xxx`` falls in here).

        The matching ancestor / node is then used as starting point for
        a relative resolution of ``relpath`` via ``abs_datapath``, so
        the ancestor's own ``datapath`` chain is consulted normally.
        """
        symbol, _, relpath = path[1:].partition(".")
        if symbol == "FORM":
            anchor = self._find_marked_datapath_ancestor(
                form=True, anchor=False, raw=raw,
            )
        elif symbol == "ANCHOR":
            anchor = self._find_marked_datapath_ancestor(
                form=False, anchor=True, raw=raw,
            )
        else:
            builder = self._resolve_builder()
            if builder is None:
                raise KeyError(
                    f"#<id>: cannot resolve {raw!r} on a node without builder"
                )
            anchor = builder.node_by_id(symbol)
        rel = f".{relpath}" if relpath else "."
        result: str = anchor.abs_datapath(rel)
        return result

    # ------------------------------------------------------------------
    # Runtime evaluation (DAT.2, slice0)
    # ------------------------------------------------------------------

    def _find_marked_datapath_ancestor(
        self,
        *,
        form: bool,
        anchor: bool,
        raw: str,
    ) -> Any:
        """Walk ancestors looking for a node carrying the requested marker.

        Markers:
            ``form=True``   — ``formId`` set OR ``form=True`` in attrs;
            ``anchor=True`` — ``_anchor`` present in attrs.

        The walk starts from this node itself. Raises ``KeyError`` if
        no ancestor satisfies the marker.
        """
        # ``current`` typed as Any for the same reason explained in
        # _compose_relative_datapath: mixin analysed in isolation.
        current: Any = self
        while current is not None:
            attrs = current.attr
            if form and (attrs.get("formId") is not None or attrs.get("form") is True):
                return current
            if anchor and "_anchor" in attrs:
                return current
            current = current.parent_node
        marker = "FORM" if form else "ANCHOR"
        raise KeyError(f"#{marker}: no marked ancestor found for {raw!r}")

    def get_relative_data(
        self,
        path: str,
        autocreate: bool = False,
        default: Any = None,
    ) -> Any:
        """Read the datastore at ``path`` resolved relative to this node.

        ``path`` is composed via :meth:`abs_datapath` into an absolute
        path on :attr:`data`; it accepts the same syntactic forms
        (absolute, relative ``.x``, ``#FORM``, ``#ANCHOR``,
        ``#<node_id>``, with or without the ``^``/``=`` prefix).

        When ``autocreate=True``, a ``None`` value at ``path`` (missing or
        explicitly ``None``) is seeded with ``default`` before the read —
        the two cases are intentionally not distinguished.
        """
        data = self.data
        abs_path = self.abs_datapath(path)
        if autocreate and data.get_item(abs_path) is None:
            data.set_item(abs_path, default)
        return data.get_item(abs_path, default=default)

    def set_relative_data(
        self,
        path: str,
        value: Any,
        attributes: dict[str, Any] | None = None,
        fired: bool = False,
        reason: Any = None,
    ) -> None:
        """Write ``value`` into the datastore at ``path``.

        ``path`` is composed via :meth:`abs_datapath` into an absolute
        path on :attr:`data` (same forms as :meth:`get_relative_data`).
        ``attributes``/``fired``/``reason`` are forwarded to
        ``Bag.set_item`` as the underscore-prefixed parameters. ``reason``
        is polymorphic: the subscriber receives whatever object is
        passed. Legacy parity (``gnrdomsource.js`` ``reason == null ?
        true``): an omitted ``reason`` becomes ``True``, so a plain write
        declares itself the origin; pass ``reason=False`` (``PUT``) to
        override.
        """
        abs_path = self.abs_datapath(path)
        self.data.set_item(
            abs_path,
            value,
            _attributes=attributes,
            _fired=fired,
            _reason=True if reason is None else reason,
        )

    def fire_event(
        self,
        path: str,
        value: Any = True,
        attributes: dict[str, Any] | None = None,
        reason: Any = None,
    ) -> None:
        """Write ``value`` to ``path`` marking the event as ``fired``.

        Legacy shortcut for ``set_relative_data(..., fired=True)``.
        Used when the write is a notification more
        than a data mutation; the ``_fired`` flag flows through the
        Bag subscribe pipeline so downstream consumers can distinguish
        events meant as triggers from ordinary value updates.
        """
        self.set_relative_data(
            path, value, attributes=attributes, fired=True, reason=reason,
        )

    # ------------------------------------------------------------------
    # Reactive DSL macros (uppercase by design) — legacy gnrlang.js parity
    # ------------------------------------------------------------------
    #
    # SET/GET/PUT/FIRE are the write/read vocabulary a data-element func uses
    # on its ``node`` (e.g. ``node.SET(".total", x)``). They are thin aliases
    # of set_relative_data/get_relative_data with the reason/fired constants
    # pre-wired; the flags travel through the genro_bag subscribe pipeline,
    # which still carries them, and nothing in this package acts on them. The
    # UPPERCASE is deliberate (not a style slip): the node carries dozens of
    # lowercase methods, and these few must stand out as the DSL operations —
    # continuity with the legacy JS where developers recognise
    # ``SET .x = ...`` / ``FIRE``.

    def SET(self, path: str, value: Any) -> None:
        """Write: ``set_relative_data`` with the default reason.

        The omitted reason becomes ``True`` (the write is its own origin),
        per :meth:`set_relative_data` legacy parity.
        """
        self.set_relative_data(path, value)

    def GET(self, path: str) -> Any:
        """Read: ``get_relative_data(path)``."""
        return self.get_relative_data(path)

    def PUT(self, path: str, value: Any) -> None:
        """Quiet write: ``set_relative_data`` with ``reason=False``.

        Unlike :meth:`SET`, ``PUT`` declares itself NOT the origin of the
        change (legacy ``reason=False``), so an originating widget would not
        bounce back on its own write.
        """
        self.set_relative_data(path, value, reason=False)

    def FIRE(self, path: str, value: Any = True) -> None:
        """Event write: ``set_relative_data`` with ``fired=True``.

        Value defaults to ``True``; the ``_fired`` flag flows through the bag
        subscribe pipeline so downstream consumers can tell triggers from
        ordinary value updates.
        """
        self.set_relative_data(path, value, fired=True)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attribute access to the active builder.

        ``node.div('hello')`` becomes ``builder._command_on_node(...)``
        when the active builder carries a tag named ``div`` in its
        schema. The grammar semantics (data-element field mapping,
        ``node_id`` uniqueness, sub-builder switch) live in the shared
        wrapper both entry points converge on — this is pure routing.
        The dialect-prefix escape works for tags as it does for
        attributes: ``node.html_label(...)`` dispatches the ``label``
        element — needed where the node API shadows a tag name
        (``label`` is BagNode API, this fallback never fires for it).
        If no grammar tag matches, fall back to a ``@container``
        dispatched via the active builder (legacy gnrwebstruct parity).
        """
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        builder = self._resolve_builder()
        if builder is None:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        original_tag = _schema_tag(builder, name)
        if original_tag is None:
            struct = _dispatch_container(builder, self, name)
            if struct is not None:
                return struct
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        def element_call(*args: Any, node_position: Any = None, **attrs: Any) -> Any:
            return builder._command_on_node(
                self, original_tag, *args,
                node_position=node_position, **attrs,
            )

        return element_call

    def __dir__(self) -> list[str]:
        """Expose schema tag names for autocompletion (original case)."""
        base = set(super().__dir__())
        builder = self._resolve_builder()
        if builder is not None:
            base.update(builder._schema_tag_names.values())
        return sorted(base)


class _SourceBagMixin:
    """Builder-aware logic for bags: schema dispatch via __getattribute__.

    Bag itself does not use __slots__, so ``_builder`` lives in
    ``__dict__`` on the concrete class.
    """

    __slots__ = ()

    def __getattribute__(self, name: str) -> Any:
        """Resolve attribute lookup with grammar priority.

        Order:
            1. dunder / private (``_<name>``) → normal lookup (fast path);
               this also covers infrastructure attributes inherited from
               genro_bag (``_node_class``, ``_container_class``, ...).
            2. ``bag_<name>`` → strip prefix and look up the underlying Bag.
            3. ``_builder`` set and ``name`` in its schema → grammar dispatch.
            4. fallback to normal lookup.
        """
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name.startswith("bag_"):
            return super().__getattribute__(name[4:])
        try:
            builder = super().__getattribute__("_builder")
        except AttributeError:
            builder = None
        if builder is not None:
            original_tag = _schema_tag(builder, name)
            if original_tag is not None:
                return builder._bag_call(self, original_tag)
        return super().__getattribute__(name)

    def __getattr__(self, name: str) -> Any:
        """Fallback after the regular attribute lookup fails: dispatch a
        ``@container`` via the active builder (legacy gnrwebstruct
        parity).
        """
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        struct = _dispatch_container(getattr(self, "_builder", None), self, name)
        if struct is not None:
            return struct
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __dir__(self) -> list[str]:
        """Expose schema tag names alongside the regular Bag API (original case)."""
        base = set(super().__dir__())
        builder = getattr(self, "_builder", None)
        if builder is not None:
            base.update(builder._schema_tag_names.values())
        return sorted(base)


class SourceBagNode(BagNode, _SourceBagNodeMixin):
    """BagNode with builder-aware attribute dispatch."""

    __slots__ = ("_builder", "_target_id")

    # Type annotations for the __slots__ above so type checkers recognize
    # them as members (slots alone are not typed). ``_builder`` holds the
    # active builder instance; ``_target_id`` the per-document serial
    # (assigned lazily by ``BuilderBase.target_id``, read with getattr —
    # an unset slot raises and ``__getattr__`` re-raises for ``_`` names).
    _builder: Any
    _target_id: str


class SourceBag(Bag, _SourceBagMixin):
    """Bag with builder-aware attribute dispatch.

    The builder instantiates its ``_source_class`` (this class by
    default, or a subclass) as ``self.source``; ``new_root`` returns a
    detached one for offline subtree building. A subclass declares the
    class of its nodes in ``_node_class`` and keeps this constructor
    signature: the builder calls it as ``cls(builder=...)``.
    """

    _node_class: type[BagNode] = SourceBagNode

    def __init__(
        self,
        source: dict[str, Any] | None = None,
        *,
        builder: Any = None,
    ):
        """Initialize the bag and attach the active builder.

        Args:
            source: Optional dict to seed the Bag (mirrors ``Bag.__init__``).
            builder: BuilderBase instance whose schema drives attribute
                dispatch on this bag (and on nodes attached to it).
        """
        super().__init__(source=source)
        self._builder = builder


# SourceBag travels on the TYTX wire as "::X" with __cls "SourceBag"
# (genro-bag 0.26.0): its name joins the subtype dictionary of its type.
# The name already owned by another class is a collision.
if get_subtype_dict(SourceBag.__tytx_suffix__).get("SourceBag", SourceBag) is not SourceBag:
    raise ValueError("TYTX subtype name 'SourceBag' is already registered for another class")
set_subtype_dict(
    SourceBag.__tytx_suffix__,
    {**get_subtype_dict(SourceBag.__tytx_suffix__), "SourceBag": SourceBag},
)
