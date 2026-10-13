# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Builder package — re-exports all public and test-used symbols.

The package is the import surface: ``from genro_builders.builder import X``
works regardless of which module inside actually defines ``X``.
"""

from ._decorators import (
    abstract,
    component,
    element,
    container,
)
from ._validators import Range, Regex
from .base import BuilderBase
from .source_bag import SourceBag, SourceBagNode
from .target_wrapper import TargetWrapper

from genro_builders.builder.custom_types import CustomTypes

__all__ = [
    "CustomTypes",
    "BuilderBase",
    "SourceBag",
    "SourceBagNode",
    "TargetWrapper",
    "Range",
    "Regex",
    "abstract",
    "component",
    "element",
    "container",
]
