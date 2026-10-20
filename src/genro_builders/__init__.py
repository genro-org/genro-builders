# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Builder system for genro-bag — grammar and bag layering.

Builders declare a domain-specific grammar via decorators (@element,
@abstract). Sub-builders and data-elements are ordinary @element marked
in their ``_meta`` (``subbuilder`` / ``data_element``). A builder is also
the document: it owns the create/render lifecycle on top of its grammar.

Core classes:
    BuilderBase: Grammar base — @element, @abstract (sub-builders and
        data-elements are @element with the matching ``_meta`` marker).
        ``create()`` populates ``self.source``, ``render()`` serializes
        it through the renderer of the requested mode.
    SourceBag / SourceBagNode: the bag/node pair. Carry the ``_builder``
        slot and the grammar-aware attribute resolution.

A builder that reads pointers owns its own datastore: ``builder.data``,
one flat Bag, reachable from any node as ``node.data``.
"""

from genro_builders.builder import BuilderBase, SourceBag, SourceBagNode, container

__version__ = "0.30.0"

from genro_builders.builder.custom_types import CustomTypes

__all__ = [
    "CustomTypes",
    "BuilderBase",
    "SourceBag",
    "SourceBagNode",
    "container",
]
