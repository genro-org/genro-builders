# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Named, reusable constraints for Python signatures and portable grammars."""

from __future__ import annotations

import keyword
import math
import re
from dataclasses import dataclass
from typing import Annotated, Any, get_args

_RESERVED_NAMES = frozenset({
    "register", "validate", "resolve", "to_dict", "from_dict", "toJSON", "fromJSON",
    "constructor", "toString", "toLocaleString", "valueOf", "hasOwnProperty",
    "isPrototypeOf", "propertyIsEnumerable",
})

def _contains_custom_type(annotation: Any) -> bool:
    return isinstance(annotation, _CustomType) or any(
        _contains_custom_type(arg) for arg in get_args(annotation)
    )


def _check_custom_type_names(schema: Any) -> None:
    """Reject ambiguous names while composing decorated/imported declarations."""
    from ._grammar_load import _custom_types

    names: dict[str, _CustomType] = {}

    def collect(annotation: Any) -> None:
        if isinstance(annotation, _CustomType):
            if annotation.name in names and names[annotation.name] != annotation:
                raise ValueError(f"conflicting custom type {annotation.name!r}")
            names[annotation.name] = annotation
        for arg in get_args(annotation):
            collect(arg)

    catalogs_seen: set[int] = set()
    for node in [*schema.get_nodes(), *schema["_abstracts"].get_nodes()]:
        signature = node.get_attr("declaration_signature")
        if signature is not None:
            for param in signature.parameters.values():
                collect(param.annotation)
        catalog = node.get_attr("custom_types")
        if catalog and id(catalog) not in catalogs_seen:
            catalogs_seen.add(id(catalog))
            for alias in _custom_types(catalog)._types.values():
                collect(alias)


@dataclass(frozen=True)
class _CustomType:
    name: str
    base: Any
    annotation: Any

    def __call__(self, value: Any) -> None:
        from ._utilities import _check_type

        if self.base in (int, float):
            numeric_types = (int,) if self.base is int else (int, float)
            if type(value) not in numeric_types or (type(value) is float and not math.isfinite(value)):
                raise TypeError(f"{self.name}: expected a finite {self.base.__name__}")
        if not _check_type(value, self.base, strict_json_primitives=True):
            raise TypeError(f"{self.name}: expected {self.base}")
        try:
            self.annotation(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.name}: {exc}") from exc


class CustomTypes:
    """Register ``(name, type, annotation)`` and use ``ct.name`` in signatures.

    Constraints apply to the original input, before pointer resolution.
    Registration is explicit and never replaces an existing name. Export
    accepts only portable validator descriptors (currently Regex and Range).
    """

    __slots__ = ("_types",)

    def __init__(self) -> None:
        self._types: dict[str, Any] = {}

    def register(self, name: str, type: Any, annotation: Any) -> Any:
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name)
                or keyword.iskeyword(name) or name in _RESERVED_NAMES
                or hasattr(self.__class__, name)):
            raise ValueError(f"invalid or reserved custom type name: {name!r}")
        if name in self._types:
            raise ValueError(f"custom type already registered: {name!r}")
        if not callable(annotation):
            raise TypeError("annotation must be a callable validator")
        alias = Annotated[type, _CustomType(name, type, annotation)]
        self._types[name] = alias
        return alias

    def __getattr__(self, name: str) -> Any:
        try:
            return self._types[name]
        except KeyError:
            raise AttributeError(f"unknown custom type: {name!r}") from None

    def to_dict(self) -> dict[str, Any]:
        """Export an independent portable catalog, suitable for JSON."""
        from ._grammar_export import _annotation_form

        catalog: dict[str, Any] = {}
        for name, alias in self._types.items():
            _annotation_form(alias, f"custom_types.{name}", catalog)
        return catalog

    def validate(self, name: str, value: Any) -> None:
        """Apply a registered constraint explicitly, for handwritten helpers."""
        alias = self.__getattr__(name)
        get_args(alias)[-1](value)

    @classmethod
    def from_dict(cls, catalog: dict[str, Any]) -> CustomTypes:
        """Load the same catalog consumed by the JavaScript registry."""
        from ._grammar_load import _custom_types

        return _custom_types(catalog)
