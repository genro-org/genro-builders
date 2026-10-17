# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Explicit pointer suffixes. Static Python output never evaluates JavaScript."""
import re
import math
from decimal import Decimal

SLOT = re.compile(r"\{(\??[A-Za-z_][A-Za-z0-9_]*|\?)?\}")

def expression_slots(body):
    """Collect slots outside quoted literals/comments/regex; never evaluate JavaScript."""
    slots, index, operand = [], 0, True
    while index < len(body):
        char = body[index]
        if char in "\"'`":
            index += 1
            while index < len(body):
                if body[index] == "\\":
                    index += 2
                elif body[index] == char:
                    index += 1
                    break
                else:
                    index += 1
            operand = False
            continue
        if body.startswith("//", index):
            end = body.find("\n", index)
            index = len(body) if end < 0 else end
            continue
        if body.startswith("/*", index):
            end = body.find("*/", index + 2)
            index = len(body) if end < 0 else end + 2
            continue
        if char == "/" and operand:
            index += 1
            bracket = False
            while index < len(body):
                current = body[index]
                index += 1
                if current == "\\":
                    index += 1
                elif current == "[":
                    bracket = True
                elif current == "]":
                    bracket = False
                elif current == "/" and not bracket:
                    break
            while index < len(body) and body[index].isascii() and body[index].isalpha():
                index += 1
            operand = False
            continue
        match = SLOT.match(body, index)
        if match:
            name = match[1] or ""
            if name.startswith("?"):
                raise ValueError("Optional slots are supported in pointer templates only")
            slots.append(name)
            index = match.end()
            operand = False
            continue
        word = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", body[index:])
        if word:
            index += len(word[0])
            operand = word[0] in ("return", "typeof", "void", "delete", "new", "in", "instanceof", "yield", "await")
            continue
        index += 1
        if not char.isspace():
            operand = char in "([{,:;=!?&|+*%~<>/-"
    return slots


def pointer_transform(value):
    if not isinstance(value, str) or not value.startswith(("^", "=")) or value.startswith("=="):
        return None
    if ":" not in value:
        return None
    pointer, body = value.split(":", 1)
    expression = body.startswith("=")
    return pointer, expression, body[1:] if expression else body


def _template_text(value):
    """Match JavaScript's scalar text for booleans and finite JSON numbers."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if not math.isfinite(value):
            return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
        if value == 0:
            return "0"
        if 1e-6 <= abs(value) < 1e21:
            text = format(Decimal(str(value)), 'f')
            return text.rstrip('0').rstrip('.') if '.' in text else text
        mantissa, exponent = repr(value).lower().split('e')
        return f"{mantissa.removesuffix('.0')}e{int(exponent):+d}"
    return str(value)


def pointer_template(body, read):
    result, blocked, index = [], False, 0
    while index < len(body):
        if body[index] not in "{}":
            result.append(body[index])
            index += 1
            continue
        match = SLOT.match(body, index)
        if match is None:
            raise ValueError("Invalid pointer template placeholder")
        slot = match[1] or ""
        optional = slot.startswith("?")
        value = read(slot[1:] if optional else slot)
        if value is None or (value == "" and not optional):
            blocked = True
        else:
            result.append(_template_text(value))
        index = match.end()
    return None if blocked else "".join(result)


def resolve_pointer_items(items, current):
    """Resolve a fresh attribute graph from already read, typed input values."""
    values, active = {}, []

    def resolve(name):
        if name in values:
            return values[name]
        if name not in items:
            raise ValueError(f"Referenced Source attribute {name!r} does not exist")
        if name in active:
            raise ValueError(f"Cyclic attribute dependency: {' -> '.join(active + [name])}")
        active.append(name)
        try:
            transform = pointer_transform(items[name]) if isinstance(name, str) else None
            result = current[name]
            if transform:
                _, expression, body = transform
                def read(key):
                    return resolve(key) if key else current[name]
                if expression:
                    for key in expression_slots(body):
                        read(key)
                    result = None
                else:
                    result = pointer_template(body, read)
                    if current[name] is None:
                        result = None
            values[name] = result
            return result
        finally:
            active.pop()

    return {name: resolve(name) for name in items}


def pointer_dependencies(node, raw):
    """Transitive Source attribute names; recompute after rebinding. No subscriptions."""
    items = dict(node.attr)
    items.update(node.fixed_attr_items())
    seen, active = set(), []

    def visit(value):
        transform = pointer_transform(value)
        if not transform:
            return
        _, expression, body = transform
        names = []
        if expression:
            names = expression_slots(body)
        else:
            pointer_template(body, lambda key: names.append(key) or '')
        for name in filter(None, names):
            if name not in items:
                raise ValueError(f"Referenced Source attribute {name!r} does not exist")
            if name in active:
                raise ValueError(f"Cyclic attribute dependency: {' -> '.join(active + [name])}")
            if name in seen:
                continue
            active.append(name)
            visit(items[name])
            active.pop()
            seen.add(name)
    visit(raw)
    return seen
