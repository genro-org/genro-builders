# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Grammar mixin: element dispatch, validation, schema access.

Interprets the schema defined by decorators to create and validate nodes.
Handles ``__getattr__`` lookup, element and subbuilder creation (the
three data-elements are ordinary elements marked ``_meta['data_element']``,
created through the same path), child placement, all validation checks
(call_args, sub_tags, parent_tags), and schema introspection
(``__contains__``, ``_get_schema_info``, ``__iter__``).
"""

from __future__ import annotations

import inspect
import re
from typing import TYPE_CHECKING, Any

from genro_bag import Bag

from ._utilities import (
    FRAMEWORK_CALL_KWARGS,
    _check_type,
    _parse_parent_tags_spec,
    _parse_sub_tags_spec,
)

# Same ``${name}`` shape as the render-time templates (base._TEMPLATE_RE),
# but resolved here at build time against the new node's attributes.
_COLLECTION_KEY_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

if TYPE_CHECKING:
    from genro_bag import BagNode

    from .source_bag import SourceBagNode


class _GrammarMixin:
    """Mixin for element dispatch, creation, validation, and schema access."""

    # -----------------------------------------------------------------------
    # Bag delegation
    # -----------------------------------------------------------------------

    def _bag_call(self, bag: Bag, name: str) -> Any:
        """Return callable that creates a schema element in the bag.

        Precondition: name is in self._schema. Positional args reach the
        wrapper raw: the data-element field mapping needs them.
        """
        handler = self.__getattr__(name)
        return lambda *args, node_label=None, node_position=None, **attr: handler(
            bag,
            *args,
            _tag=name,
            node_label=node_label,
            node_position=node_position,
            **attr,
        )

    # -----------------------------------------------------------------------
    # Element dispatch
    # -----------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Look up tag in _schema and return handler with validation.

        The wrapper is the single semantic path for element creation:
        both entry points — a node (``body.div(...)``, via
        ``_command_on_node``) and a bag (``root.div(...)``, via
        ``__getattribute__`` → ``_bag_call``) — converge here, so the
        grammar semantics (data-element field mapping, ``node_id``
        uniqueness, sub-builder switch) apply identically to both.
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        def wrapper(destination_bag: Bag, *args: Any, node_tag: str = name, **kwargs: Any) -> Any:
            try:
                info = self._get_schema_info(node_tag)
            except KeyError as err:
                raise AttributeError(f"'{type(self).__name__}' has no element '{node_tag}'") from err

            meta = info.get("_meta") or {}
            if "data_element" in meta:
                # Map the data-element positional fields (e.g.
                # dataSetter(destination, value)) onto their schema field
                # names so they reach the named parameters instead of
                # collapsing into node_value. Fields (incl. a Bag ``value``)
                # stay flat as attrs; a Bag attribute is not walked, so the
                # data payload is not captured into the source tree.
                fields = list(info.get("call_args_validations") or {})
                for field_name, field_value in zip(fields, args, strict=False):
                    kwargs[field_name] = field_value
                node_value = None
            else:
                node_value = args[0] if args else kwargs.get("node_value")

            # node_id is the document's primary key: uniqueness is
            # guaranteed by the ROOT builder (one namespace per document,
            # sub-builder subtrees included), whichever entry point and
            # whichever dialect creates the node.
            node_id = kwargs.get("node_id")
            if node_id is not None:
                root_builder = getattr(destination_bag.root, "_builder", None)
                if root_builder is not None:
                    try:
                        root_builder.node_by_id(node_id)
                    except KeyError:
                        pass
                    else:
                        raise ValueError(f"Duplicate node_id '{node_id}'.")

            # Validate original kwargs BEFORE the method call
            self._validate_call_args(info, node_value, kwargs, node_tag)

            # Element: no adapter, register directly with original kwargs
            kwargs.pop("node_value", None)
            kwargs.pop("_tag", None)  # internal marker, never an attribute
            child = self._add_element(destination_bag, node_value, node_tag=node_tag, **kwargs)

            # Sub-builder element: ``_meta['subbuilder']`` names the dialect
            # active from this node down — a registry name (``"svg"``) or a
            # parameter reference (``"kwarg:attr"``, resolved against the
            # recipe kwargs here, the one point that sees them). Switch the
            # child's active builder (the node carries its own
            # ``_builder``); the descent then resolves the foreign grammar
            # instead of the host's.
            sub_name = meta.get("subbuilder")
            if sub_name is not None:
                sub_target = self._resolve_subbuilder_reference(sub_name, kwargs, node_tag)
                if sub_target is not None:
                    child._builder = self.get_subbuilder(sub_target)
            return child

        return wrapper

    def _resolve_subbuilder_reference(
        self, spec: str, kwargs: dict[str, Any], node_tag: str,
    ) -> str | type | None:
        """Resolve a ``_meta['subbuilder']`` spec to a get_subbuilder target.

        Two forms. No colon → ``spec`` is a registry name, returned as-is
        (the historical path). ``kwarg:attr`` → the grammar comes from the
        call site: take the value the recipe passed as ``kwarg`` and read
        ``attr`` from it — that class governs the subtree. The kwarg left
        unset means NO switch (returns None): the node stays a leaf of the
        host grammar. A set kwarg missing the declared attribute, or whose
        attribute is not a class, is an authoring error raised at the
        recipe line.
        """
        if ":" not in spec:
            return spec
        kwarg, attr_name = spec.split(":", 1)
        value = kwargs.get(kwarg)
        if value is None:
            return None
        grammar = getattr(value, attr_name, None)
        if grammar is None:
            raise ValueError(
                f"'{node_tag}': subbuilder reference {spec!r} — the object "
                f"passed as {kwarg!r} has no attribute {attr_name!r}",
            )
        if not isinstance(grammar, type):
            raise ValueError(
                f"'{node_tag}': subbuilder reference {spec!r} — "
                f"{kwarg}.{attr_name} must be a class, got "
                f"{type(grammar).__name__}",
            )
        return grammar

    def _add_element(
        self,
        build_where: Bag,
        node_value: Any = None,
        node_label: str | None = None,
        node_tag: str = "",
        **attr: Any,
    ) -> BagNode:
        """Add an element node to the bag.

        Called by the wrapper after optional adapter transformation.

        Args:
            build_where: The destination Bag where the node will be created.
            node_value: Node content (positional). Becomes node.value.
            node_label: Optional explicit label for the node.
            node_tag: The tag name for the element.
            **attr: Node attributes.
        """
        return self.set_child(build_where, node_tag, node_value, node_label=node_label, **attr)

    def set_child(
        self,
        build_where: Bag,
        node_tag: str,
        node_value: Any = None,
        node_label: str | None = None,
        node_position: str | int | None = None,
        **attr: Any,
    ) -> BagNode:
        """Create a child node in the target Bag with validation.

        Public entry point for the grammar machine: every ``body.div(...)``,
        ``body.span(...)`` etc. ultimately lands here. Use it directly when
        you need to attach a node whose tag is computed at runtime (rather
        than spelled out as a method name), e.g. when injecting a subtree
        pre-built via ``BuilderBase.new_root``.

        The label comes from what the PARENT declares about this tag:

        - a collection (``collection_key``) → the child's natural key;
        - declared at most once (``x[1]``, ``x[0:1]``) → the tag itself,
          since no ordinal is needed to tell one sibling from another;
        - anything else → ``_auto_label`` (``tag_0``, ``tag_1``, ...).

        In the first two cases the label belongs to the grammar, so an
        explicit ``node_label`` raises rather than being silently honoured,
        and so does a second node claiming a label already taken.

        Raises ValueError if validation fails, KeyError if parent tag not in schema.
        """
        parent_node = build_where.parent_node
        parent_check: tuple[BagNode, dict] | None = None
        if parent_node and parent_node.node_tag:
            try:
                parent_check = (parent_node, self._get_schema_info(parent_node.node_tag))
            except KeyError:
                # A subbuilder envelope belongs to the HOST grammar: the
                # embedded grammar need not declare its tag. The envelope
                # is transparent to containment anyway, so it simply
                # imposes nothing on its children here.
                if not parent_node._get_meta("subbuilder"):
                    raise

        child_info = self._get_schema_info(node_tag)
        self._validate_parent_tags(child_info, parent_node)

        # The element's schema ``_meta`` rides onto the node as a single
        # ``_meta`` attribute (read uniformly via ``node._get_meta``).
        # Done here — the one point both dispatch paths (bag root and
        # node child) converge — so it is never duplicated nor missed on
        # a root node. An explicit ``_meta`` in ``attr`` is left as-is.
        if "_meta" not in attr:
            meta = child_info.get("_meta")
            if meta:
                attr["_meta"] = meta

        # The namespace prefix ``ns`` (a first-class schema attribute, not
        # ``_meta``) rides onto the node the same way, so the renderer can
        # compose ``<ns>:<tag>``. Only when declared: nodes without a
        # namespace stay clean. An explicit ``ns`` in ``attr`` wins.
        if "ns" not in attr:
            ns = child_info.get("ns")
            if ns:
                attr["ns"] = ns

        collection_key = parent_check[1].get("collection_key") if parent_check else None
        if collection_key:
            if node_label is not None:
                raise ValueError(
                    f"'{node_tag}': node_label is not allowed in a collection "
                    f"(parent declares collection_key={collection_key!r}); "
                    "the natural key is the label",
                )
            node_label = self._resolve_collection_key(collection_key, node_tag, attr)
            if build_where.node(node_label) is not None:
                raise ValueError(
                    f"duplicate collection key {node_label!r} among "
                    f"'{node_tag}' siblings",
                )
        elif parent_check is not None and self._is_singleton(parent_check[1], node_tag):
            if node_label is not None:
                raise ValueError(
                    f"'{node_tag}': node_label is not allowed on a singleton "
                    f"(its parent declares it at most once); the tag is the label",
                )
            node_label = node_tag
            if build_where.node(node_label) is not None:
                raise ValueError(
                    f"'{node_tag}' is declared at most once in "
                    f"'{parent_check[0].node_tag}' and is already present",
                )
        else:
            node_label = (
                node_label
                or child_info.get("node_label")
                or self._auto_label(build_where, node_tag)
            )
        child_node = build_where.set_item(
            node_label, node_value, _attributes=dict(attr),
            node_position=node_position, node_tag=node_tag,
        )

        try:
            if parent_check is not None:
                self._validate_sub_tags(*parent_check)
            self._validate_sub_tags(child_node, child_info)
        except ValueError:
            build_where.pop(node_label)
            raise

        return child_node

    def _is_singleton(self, parent_info: dict, node_tag: str) -> bool:
        """Whether the parent declares ``node_tag`` at most once.

        Reads the MAXIMUM of the parent's compiled cardinality: ``x[1]``
        and ``x[0:1]`` are both singletons — what matters is that a second
        one cannot exist, not whether the first is mandatory. A singleton
        needs no ordinal to be told apart from its siblings, so its label
        is the tag itself (``head``, not ``head_0``).

        False when the parent declares no cardinality (a bare ``x``, the
        ``"*"`` wildcard) or when there is no parent element at all: the
        top-level children of the source root have no declared bounds.
        """
        sub_tags_compiled = parent_info.get("sub_tags_compiled")
        if not isinstance(sub_tags_compiled, dict):
            return False
        bounds = sub_tags_compiled.get(node_tag)
        return bounds is not None and bounds[1] == 1

    def _auto_label(self, build_where: Bag, node_tag: str) -> str:
        """Generate unique label for a node: tag_0, tag_1, ..."""
        n = 0
        while build_where.node(f"{node_tag}_{n}") is not None:
            n += 1
        return f"{node_tag}_{n}"

    def _resolve_collection_key(
        self, key: str, node_tag: str, attr: dict[str, Any],
    ) -> str:
        """Resolve a collection child's label from its natural key.

        ``key`` is either a ``${...}`` template over the child's
        attributes or a single attribute name. Strict: every referenced
        attribute must be present and not None, else raise — a collection
        member without its key is an authoring error, not an auto-label.
        """
        def _value(name: str) -> str:
            if attr.get(name) is None:
                raise ValueError(
                    f"'{node_tag}': collection key needs attribute "
                    f"{name!r}, which is missing",
                )
            return str(attr[name])

        if "${" in key:
            return _COLLECTION_KEY_RE.sub(lambda m: _value(m.group(1)), key)
        return _value(key)

    def _command_on_node(
        self,
        node: SourceBagNode,
        child_tag: str,
        *args: Any,
        node_position: str | int | None = None,
        **attrs: Any,
    ) -> Any:
        """Add a child to a node.

        Uses _bag_call for schema elements (handles tag renames); the
        grammar semantics live in the shared wrapper. Falls back to
        self.set_child() for unknown tags (provides validation errors).
        """
        if not isinstance(node.value, Bag):
            # Sub-bag must be the same type as the parent bag (e.g. a
            # ``SourceBagNode`` spawns a ``SourceBag`` sub-bag).
            # ``_builder`` is resolved via the node itself
            # (its slot if populated, else ancestors): this lets an
            # @subbuilder node (e.g. <svg>) propagate its own dialect
            # down into the freshly-created sub-bag instead of leaking
            # the host dialect.
            node.value = type(node.parent_bag)(
                builder=node._resolve_builder(),
            )

        if child_tag in self._schema:
            callable_handler = self._bag_call(node.value, child_tag)
            return callable_handler(
                *args,
                node_position=node_position,
                **attrs,
            )

        # Tag not in schema: use set_child() which will validate and raise.
        # This path never reaches the shared wrapper, so the node_id
        # uniqueness check runs here.
        node._check_unique_id(attrs.get("node_id"))
        return self.set_child(
            node.value,
            child_tag,
            node_value=args[0] if args else None,
            node_position=node_position,
            **attrs,
        )

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def _validate_declared_names(
        self,
        info: dict,
        attr: dict[str, Any],
        node_tag: str,
    ) -> None:
        """Reject attributes the element's signature does not declare.

        A signature without ``**kwargs`` states a closed set, exactly as it
        would in plain Python: an unexpected keyword is an error, not a new
        attribute. Declaring ``**kwargs`` is how an element opts into an
        open set -- what a markup dialect wants (``data-*``, ``aria-*``)
        and what a configuration grammar must not have, since there a typo
        is otherwise indistinguishable from a deliberate field.

        Runs before the type checks: it is the cheapest test, and reporting
        an unknown name beats reporting a type error on a name that should
        not be there at all.
        """
        if info.get("accepts_var_keyword"):
            return
        declared = info.get("declared_names")
        if declared is None:
            return  # element predating the signature contract: stay open

        unknown = sorted(
            set(attr) - set(declared) - FRAMEWORK_CALL_KWARGS
        )
        if not unknown:
            return

        accepted = ", ".join(sorted(declared)) or "(none)"
        raise ValueError(
            f"Element '{node_tag}' does not accept "
            f"{', '.join(repr(k) for k in unknown)}. "
            f"Declared attributes: {accepted}. "
            f"Add **kwargs to its signature to accept arbitrary attributes."
        )

    def _validate_custom_types(self, node: Any) -> None:
        """Recheck named input constraints before consuming an existing Source."""
        from .custom_types import _CustomType, _contains_custom_type

        # The envelope belongs to the host grammar even after the active
        # builder has switched for the subtree below it.
        owner = self
        parent = node.parent_node
        host = parent.builder if parent is not None else getattr(node.parent_bag, "_builder", None)
        if host is not None and host is not self:
            declaration = host._schema.get_node(node.node_tag)
            if declaration is not None and (declaration.get_attr("_meta") or {}).get("subbuilder"):
                owner = host
        # Legacy dynamic nodes have no declaration or named constraints.
        if owner._schema.get_node(node.node_tag) is None:
            return
        info = owner._get_schema_info(node.node_tag)
        values = dict(node.attr)
        values["node_value"] = node.value
        for name, (base, validators, _) in (info.get("call_args_validations") or {}).items():
            if name not in values:
                continue
            checks = [v for v in validators if isinstance(v, _CustomType)]
            if not checks and not _contains_custom_type(base):
                continue
            if values[name] is None:
                from ._grammar_load import _accepts_none

                signature = info.get("declaration_signature")
                if (name in (info.get("loaded_nullable_names") or ())
                        or (signature is not None and name in signature.parameters
                            and _accepts_none(signature.parameters[name].annotation))):
                    continue
            try:
                if not _check_type(values[name], base, strict_json_primitives=True):
                    raise TypeError(f"expected {base}")
                for check in checks:
                    check(values[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{node.node_tag}.{name}: {exc}") from exc

    def _validate_call_args(
        self,
        info: dict,
        node_value: Any,
        attr: dict[str, Any],
        node_tag: str = "",
    ) -> None:
        """Validate attributes and node_value. Raises ValueError if invalid."""
        self._validate_declared_names(info, attr, node_tag)

        call_args_validations = info.get("call_args_validations")
        if not call_args_validations:
            return

        errors: list[str] = []
        all_args = dict(attr)
        if node_value is not None:
            all_args["node_value"] = node_value

        # A signature read from a document follows genro-builders-js
        # (``validateElementValues``): a parameter is required by
        # presence, a supplied ``None`` is a value that only a nullable
        # annotation accepts, and ``True`` is not an int. Decorator-built schemas
        # keep the established behavior: ``None`` counts as missing.
        loaded = bool(info.get("loaded_strict_json_primitives"))
        loaded_required = info.get("loaded_required_names") or ()
        loaded_nullable = info.get("loaded_nullable_names") or ()

        for attr_name, (base_type, validators, default) in call_args_validations.items():
            attr_value = all_args.get(attr_name)

            if loaded:
                if attr_name not in all_args:
                    if attr_name in loaded_required:
                        errors.append(f"required attribute '{attr_name}' is missing")
                    continue
                if attr_value is None:
                    # The loader decided which annotations accept None
                    # (a nullable union, Any, no annotation).
                    if attr_name not in loaded_nullable:
                        errors.append(
                            f"'{attr_name}': expected {base_type}, got NoneType"
                        )
                    continue
            else:
                # Required check
                if default is inspect.Parameter.empty and attr_value is None:
                    errors.append(f"required attribute '{attr_name}' is missing")
                    continue

                if attr_value is None:
                    continue

            # Type check
            if not _check_type(attr_value, base_type, strict_json_primitives=loaded):
                errors.append(
                    f"'{attr_name}': expected {base_type}, got {type(attr_value).__name__}"
                )
                continue

            # Validator checks (Regex, Range, etc.). Only the exceptions a
            # validator raises by contract are collected as validation
            # errors; anything else is a bug in the validator and propagates.
            for v in validators:
                try:
                    v(attr_value)
                except (TypeError, ValueError) as e:
                    errors.append(f"'{attr_name}': {e}")

        if errors:
            raise ValueError("Validation failed: " + "; ".join(errors))

    def _validate_children_tags(
        self,
        node_tag: str,
        sub_tags_compiled: dict[str, tuple[int, int]] | str,
        children_tags: list[str],
    ) -> list[str]:
        """Validate a list of child tags against sub_tags spec.

        Args:
            node_tag: Tag of parent node (for error messages)
            sub_tags_compiled: Compiled sub_tags: "*" for any, or dict {tag: (min, max)}
            children_tags: List of child tags to validate

        Returns:
            List of tag names whose minimum cardinality was not met
            (required children still missing).

        Raises:
            ValueError: if tag not allowed or max exceeded
        """
        # Wildcard "*" accepts any children - no validation needed.
        # isinstance (not == "*") so mypy narrows the remaining type to dict:
        # _parse_sub_tags_spec returns "*" as its only str value, else a dict.
        if isinstance(sub_tags_compiled, str):
            return []

        bounds = {tag: list(minmax) for tag, minmax in sub_tags_compiled.items()}
        for tag in children_tags:
            minmax = bounds.get(tag)
            if minmax is None:
                raise ValueError(f"'{tag}' not allowed as child of '{node_tag}'")
            minmax[1] -= 1
            if minmax[1] < 0:
                raise ValueError(f"Too many '{tag}' in '{node_tag}'")
            minmax[0] -= 1

        # Warnings for missing required elements (min > 0 after decrement)
        return [tag for tag, (n_min, _) in bounds.items() if n_min > 0]

    def _validate_sub_tags(self, node: BagNode, info: dict) -> list[str]:
        """Validate sub_tags constraints on node's existing children.

        Raises on a child not allowed or over its maximum (incremental
        check, fired at every insertion). Returns the list of child tags
        whose MINIMUM cardinality is not yet satisfied: meaningless while
        building (the document is naturally incomplete), and reported on
        demand by ``BuilderBase.validate_source`` — a render never
        validates.

        Args:
            node: The node to validate.
            info: Schema info dict from get_schema_info().
        """
        # Subbuilder nodes are transparent containers for the embedded dialect.
        if node._get_meta("subbuilder"):
            return []

        sub_tags_compiled = info.get("sub_tags_compiled")
        if sub_tags_compiled is None:
            return []

        # Wildcard "*" accepts any children - no validation needed
        if sub_tags_compiled == "*":
            return []

        children_tags = [
            n.node_tag for n in node.value.nodes
            if self.require_sub_tag_validation(n)
        ] if isinstance(node.value, Bag) else []

        return self._validate_children_tags(
            node.node_tag, sub_tags_compiled, children_tags
        )

    def require_sub_tag_validation(self, node: BagNode) -> bool:
        """Whether ``node`` counts as a child for its parent's sub_tags check.

        Data-elements and subbuilders are structural: invisible to the
        containment grammar. Components too (CMP.5: no placement
        validation — where the caller puts them is the caller's
        responsibility; the expansion is ephemeral and never validated).
        Everything else defers to
        ``custom_require_sub_tag_validation``, the dialect hook.
        """
        meta = node._get_meta("data_element,subbuilder,component")
        if meta[0] or meta[1] or meta[2]:
            return False
        return self.custom_require_sub_tag_validation(node)

    def custom_require_sub_tag_validation(self, node: BagNode) -> bool:
        """Dialect hook: return False to exempt ``node`` from its parent's
        sub_tags validation. Default validates everything."""
        return True

    def _validate_parent_tags(
        self,
        child_info: dict,
        parent_node: BagNode | None,
    ) -> None:
        """Validate that child can be placed in parent based on parent_tags.

        Args:
            child_info: Schema info for the child element.
            parent_node: The parent node (None if adding to root).

        Raises:
            ValueError: If parent_tags is specified and parent is not in the list.
        """
        parent_tags_compiled = child_info.get("parent_tags_compiled")
        if parent_tags_compiled is None:
            return

        parent_tag = parent_node.node_tag if parent_node else None
        if parent_tag not in parent_tags_compiled:
            valid_parents = ", ".join(sorted(parent_tags_compiled))
            raise ValueError(
                f"Element cannot be placed here: parent_tags requires one of [{valid_parents}], "
                f"but parent is '{parent_tag or 'root'}'"
            )

    # -----------------------------------------------------------------------
    # Schema access
    # -----------------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        """Check if element exists in schema."""
        return self._schema.get_node(name) is not None

    def _get_schema_info(self, name: str) -> dict:
        """Return info dict for a schema element.

        The result is a dict of all schema-node attributes, extended with
        computed keys. Common keys (presence depends on element type):

            sub_tags, sub_tags_compiled, parent_tags, parent_tags_compiled,
            call_args_validations, declared_names, accepts_var_keyword,
            _meta, documentation.

        ``declared_names`` is every parameter the element's signature
        declares; ``accepts_var_keyword`` says whether it declares
        ``**kwargs``, i.e. whether that set is open.

        Sub-builder and data-element markers are not separate top-level
        keys: they live inside ``_meta`` (``_meta["subbuilder"]`` is the
        dialect name, ``_meta["data_element"]`` flags a data-element).

        Results are cached on the schema node after first access.

        Raises KeyError if element not in schema.
        """
        schema_node = self._schema.get_node(name)
        if schema_node is None:
            raise KeyError(f"Element '{name}' not found in schema")

        cached = schema_node.attr.get("_cached_info")  # type: ignore[union-attr]
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        result = dict(schema_node.attr)  # type: ignore[union-attr]
        inherits_from = result.pop("inherits_from", None)

        if inherits_from:
            abstracts_bag = self._schema["_abstracts"]
            parents = [p.strip() for p in inherits_from.split(",")]
            for parent in parents:
                abstract_attrs = abstracts_bag.get_attr(parent)
                for k, v in abstract_attrs.items():
                    if k == "inherits_from":
                        continue
                    if k == "_meta":
                        inherited = v or {}
                        current = result.get("_meta") or {}
                        result["_meta"] = {**inherited, **current}
                    elif k not in result or not result[k]:
                        result[k] = v

        sub_tags = result.get("sub_tags")
        if sub_tags is not None:
            result["sub_tags_compiled"] = _parse_sub_tags_spec(sub_tags)

        parent_tags = result.get("parent_tags")
        if parent_tags is not None:
            result["parent_tags_compiled"] = _parse_parent_tags_spec(parent_tags)

        schema_node.attr["_cached_info"] = result  # type: ignore[union-attr]
        return result

    def __iter__(self):
        """Iterate over public schema nodes (skips internal labels prefixed by '_')."""
        return (n for n in self._schema if not n.label.startswith("_"))

    def __repr__(self) -> str:
        """Show builder schema summary."""
        count = sum(1 for _ in self)
        return f"<{type(self).__name__} ({count} elements)>"

    def __str__(self) -> str:
        """Show schema structure."""
        return str(self._schema)
