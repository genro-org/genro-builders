# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Every parameter accepts a Data pointer; literal values keep their checks (#63)."""
from __future__ import annotations

import json
from typing import Annotated, Literal

import pytest

from genro_builders import BuilderBase, CustomTypes
from genro_builders.builder import Range, Regex, element
from genro_builders.builder._grammar_export import _class_schema_to_grammar_document

ct = CustomTypes()
ct.register("positive", int, Range(ge=1))


class DeploymentBuilder(BuilderBase):
    _name = "typed_pointers_contract"

    @element(sub_tags="")
    def deployment(
        self,
        name: Annotated[str, Regex(r"[a-z]+")],
        replicas: Annotated[int, Range(ge=0)] | None = None,
        strategy: Literal["RollingUpdate", "Recreate"] | None = None,
        workers: ct.positive | None = None,
    ): ...

    @element(sub_tags="")
    def count(self, node_value: int): ...


def load(tmp_path):
    path = tmp_path / "typed_pointers.json"
    path.write_text(json.dumps(_class_schema_to_grammar_document(DeploymentBuilder)))
    return type("LoadedDeployment", (BuilderBase,), {"_grammar_documents": (str(path),)})


@pytest.fixture(params=[False, True], ids=["decorated", "loaded"])
def builder(request, tmp_path):
    return (load(tmp_path) if request.param else DeploymentBuilder)()


@pytest.mark.parametrize("pointer", ["^app.value", "=app.value", "^.value", "^app.value:L"])
@pytest.mark.parametrize("parameter", ["name", "replicas", "strategy", "workers"])
def test_pointer_accepted_whatever_the_annotation(builder, parameter, pointer):
    attrs = {"name": "web", parameter: pointer}
    node = builder.source.deployment(**attrs)
    assert node.attr[parameter] == pointer


def test_pointer_accepted_as_node_value(builder):
    node = builder.source.count("^app.count")
    assert node.value == "^app.count"


@pytest.mark.parametrize(
    "attrs",
    [
        {"name": "Web"},
        {"name": "web", "replicas": -1},
        {"name": "web", "replicas": "three"},
        {"name": "web", "strategy": "Blue"},
        {"name": "web", "workers": 0},
        {"name": "web", "replicas": "==app.value"},
    ],
    ids=["regex", "range", "type", "literal", "custom-type", "double-equals-is-literal"],
)
def test_literal_values_keep_their_checks(builder, attrs):
    with pytest.raises(ValueError):
        builder.source.deployment(**attrs)
    assert len(builder.source) == 0


def test_count_literal_node_value_keeps_its_check(builder):
    with pytest.raises(ValueError):
        builder.source.count("three")


def test_pointer_on_typed_parameters_resolves_and_validates(builder):
    builder.data["app.replicas"] = 3
    builder.data["app.workers"] = 2
    node = builder.source.deployment(name="web", replicas="^app.replicas", workers="^app.workers")
    _, attrs = builder.runtime_values(node)
    assert attrs["replicas"] == 3
    assert attrs["workers"] == 2
    node.pointers()
    builder.validate_source()


def test_resolved_value_is_not_checked(builder):
    """Out of scope for #63: only what is written in the recipe is validated."""
    builder.data["app.replicas"] = "three"
    node = builder.source.deployment(name="web", replicas="^app.replicas")
    _, attrs = builder.runtime_values(node)
    assert attrs["replicas"] == "three"
