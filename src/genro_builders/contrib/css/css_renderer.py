# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""CssRenderer — renderer for the CSS dialect (level 1).

CSS rides the universal walk on ``RendererBase`` like every other
dialect: each node's ``runtime_values`` is resolved (pointers ``^``/
``=`` and explicit pointer suffixes actualized, keyword names like ``class_``
normalized), then ``rendered_item`` turns the node into a small
**dict fragment** describing what it is (``kind`` = selector / rule /
cssvar / importcss / selectorList / stylesheet). The walk stacks
those dicts into nested lists.

``finalize`` is the post-process: it receives the top-level list of
dict fragments and composes the CSS text — grouping ``cssvar`` into a
single ``:root`` block, hoisting ``@import`` to the top, grouping a
selector's rules by ``(media, supports)`` into base + nested ``@media``/
``@supports`` blocks, and emitting nested selectors. Pretty/minified
are two serialization modes here, not two code paths in the walk.

CSS is not XML, so the dicts never carry markup: the dialect emits the
``selector-list { prop: value; ... }`` syntax directly in ``finalize``.

Selector composition: structured kwargs (``tag``, ``id``, ``class``
[from ``class_``/``_class``], ``classes``, ``attr``) are validated with
strict regexes; ``raw`` is an opaque suffix joined with a leading space.

Property names translate underscore to hyphen (``font_size`` ->
``font-size``, ``_webkit_user_select`` -> ``-webkit-user-select``) — a
CSS spelling rule, unrelated to the Python-keyword normalization done
in ``runtime_values``.

Comment support: any element accepts ``comment="..."``. The renderer
emits ``/* ... */`` inline when the text fits in
``COMMENT_INLINE_MAX_LEN`` (60), otherwise as a block above the element.
"""

from __future__ import annotations

import re
from typing import Any

from ...renderer import RendererBase

COMMENT_INLINE_MAX_LEN = 60

_RE_TAG = re.compile(r"^[a-zA-Z][\w-]*$")
_RE_ID = re.compile(r"^[a-zA-Z_-][\w-]*$")
_RE_CLASS = re.compile(r"^[a-zA-Z_-][\w-]*(:{1,2}[\w-]+)*$")
_RE_ATTR_NAME = re.compile(r"^[a-zA-Z_-][\w-]*$")


class CssRenderer(RendererBase):
    """Renderer for the CSS dialect, on the universal walk.

    ``rendered_item`` returns a dict fragment per node; ``finalize``
    composes those fragments into the CSS document. The dialect-special
    layout (``:root`` for cssvars, ``@import`` hoisting, ``@media``/
    ``@supports`` grouping) lives entirely in ``finalize``.
    """

    mode = "css"

    # ------------------------------------------------------------------
    # Per-node fragment (rides the universal walk via runtime_values)
    # ------------------------------------------------------------------

    def rendered_item(
        self,
        node: Any,
        item: Any,
        runtime_attrs: dict[str, Any],
        *,
        tag: str,
        **_opts: Any,
    ) -> dict[str, Any]:
        """Turn one node into a dict fragment.

        ``runtime_attrs`` is already pointer-resolved and keyword-
        normalized by the walk. ``item`` is the list of child fragments
        (for selector / stylesheet) or the resolved leaf value (cssvar
        carries its name there). Composition happens in ``finalize``.
        """
        attrs = dict(runtime_attrs)
        comment = attrs.pop("comment", None)
        children = item if isinstance(item, list) else []

        if tag == "stylesheet":
            return {"kind": "stylesheet", "body": children}
        if tag == "selector":
            return {
                "kind": "selector",
                "compound": self._compound(attrs),
                "comment": comment,
                "body": children,
            }
        if tag == "selectorList":
            return {
                "kind": "selectorList",
                "compounds": [c["compound"] for c in children if c["kind"] == "selector"],
                "comment": comment,
                "body": children,
            }
        if tag == "rule":
            media = attrs.pop("media", None)
            supports = attrs.pop("supports", None)
            return {
                "kind": "rule",
                "media": media,
                "supports": supports,
                "props": self._properties(attrs),
            }
        if tag == "cssvar":
            name = item if not isinstance(item, list) and item is not None else ""
            return {
                "kind": "cssvar",
                "name": str(name),
                "value": attrs.pop("value", ""),
                "comment": comment,
            }
        if tag == "importcss":
            return {
                "kind": "importcss",
                "url": attrs.pop("url", None),
                "layer": attrs.pop("layer", None),
                "supports": attrs.pop("supports", None),
                "media": attrs.pop("media", None),
                "comment": comment,
            }
        raise ValueError(f"css: unknown element {tag!r}")

    # ------------------------------------------------------------------
    # Selector compound + properties (pure, from resolved attrs)
    # ------------------------------------------------------------------

    def _compound(self, attrs: dict[str, Any]) -> str:
        """Build a selector compound from resolved structured kwargs."""
        tag = attrs.pop("tag", None)
        sel_id = attrs.pop("id", None)
        single_class = attrs.pop("class", None)
        many_classes = attrs.pop("classes", None)
        attr_map = attrs.pop("attr", None)
        raw = attrs.pop("raw", None)

        if single_class is not None and many_classes is not None:
            raise ValueError(
                "selector: pass either class_ (single) or classes (list), not both",
            )

        parts: list[str] = []
        if tag is not None:
            if not isinstance(tag, str) or not _RE_TAG.match(tag):
                raise ValueError(f"selector tag {tag!r}: must match [a-zA-Z][\\w-]*")
            parts.append(tag)
        if sel_id is not None:
            if not isinstance(sel_id, str) or not _RE_ID.match(sel_id):
                raise ValueError(f"selector id {sel_id!r}: must match [a-zA-Z_-][\\w-]*")
            parts.append(f"#{sel_id}")
        class_list: list[str] = []
        if single_class is not None:
            if not isinstance(single_class, str):
                raise ValueError(
                    f"selector class_ {single_class!r}: must be a string; "
                    "use classes=[...] for multiple",
                )
            class_list = [single_class]
        elif many_classes is not None:
            if not isinstance(many_classes, (list, tuple)):
                raise ValueError(f"selector classes {many_classes!r}: must be a list")
            class_list = list(many_classes)
        for cls in class_list:
            if not isinstance(cls, str) or not _RE_CLASS.match(cls):
                raise ValueError(
                    f"selector class {cls!r}: must match "
                    "[a-zA-Z_-][\\w-]*(:{1,2}[\\w-]+)* "
                    "(no spaces, no dots, no combinators)",
                )
            parts.append(f".{cls}")
        if attr_map is not None:
            if not isinstance(attr_map, dict):
                raise ValueError(f"selector attr {attr_map!r}: must be a dict")
            for name, value in attr_map.items():
                if not isinstance(name, str) or not _RE_ATTR_NAME.match(name):
                    raise ValueError(
                        f"selector attr name {name!r}: must match [a-zA-Z_-][\\w-]*",
                    )
                parts.append(f"[{name}]" if value is None else f'[{name}="{value}"]')

        compound = "".join(parts)
        if raw is not None:
            raw_str = str(raw)
            return f"{compound} {raw_str}" if compound else raw_str
        if not compound:
            raise ValueError(
                "selector: at least one of tag/id/class_/classes/attr/raw "
                "must be provided",
            )
        return compound

    def _properties(self, attrs: dict[str, Any]) -> list[str]:
        """One ``css-name: value;`` per property kwarg (underscore->hyphen)."""
        return [f'{name.replace("_", "-")}: {value};' for name, value in attrs.items()]

    # ------------------------------------------------------------------
    # Finalize (the post-process: dict fragments -> CSS text)
    # ------------------------------------------------------------------

    def finalize(
        self,
        result: Any,
        target: Any,
        *,
        pretty: bool = True,
        indent: str = "  ",
        **_opts: Any,
    ) -> Any:
        """Compose top-level dict fragments into the CSS document.

        ``result`` is the top-level list of fragments from the walk (a
        single fragment for a subtree render is wrapped). Top-level
        cssvars are gathered into one ``:root`` block; inside a
        ``stylesheet`` imports are hoisted first. The text is then
        consumed via the base ``finalize`` (path / writable / callable).
        """
        fragments = result if isinstance(result, list) else [result]
        lines: list[str] = []
        self._emit_sequence(fragments, lines, pretty=pretty, indent=indent, depth=0)
        text = (
            "\n".join(lines) + ("\n" if lines else "")
            if pretty
            else "".join(lines)
        )
        return super().finalize(text, target)

    def _emit_sequence(
        self,
        fragments: list[dict[str, Any]],
        lines: list[str],
        *,
        pretty: bool,
        indent: str,
        depth: int,
        in_stylesheet: bool = False,
    ) -> None:
        """Emit a sequence of top-level fragments.

        Inside a stylesheet, ``importcss`` directives come first in
        insertion order; then cssvars and selectors in natural position.
        Consecutive top-level cssvars share one ``:root`` block; any
        non-cssvar fragment flushes the buffer. ``importcss`` outside a
        stylesheet is a contract violation (``@import`` only inside one).
        """
        if in_stylesheet:
            imports = [f for f in fragments if f["kind"] == "importcss"]
            rest = [f for f in fragments if f["kind"] != "importcss"]
            for imp in imports:
                self._emit_import(imp, lines, pretty=pretty, indent=indent, depth=depth)
            fragments = rest

        cssvar_buffer: list[dict[str, Any]] = []

        def flush() -> None:
            if cssvar_buffer:
                self._emit_root_cssvars(
                    cssvar_buffer, lines, pretty=pretty, indent=indent, depth=depth,
                )
                cssvar_buffer.clear()

        for frag in fragments:
            kind = frag["kind"]
            if kind == "cssvar":
                cssvar_buffer.append(frag)
                continue
            if kind == "importcss" and not in_stylesheet:
                raise ValueError(
                    "importcss must be a child of stylesheet; open one first "
                    "(root.stylesheet().importcss(...)).",
                )
            flush()
            if kind == "stylesheet":
                self._emit_sequence(
                    frag["body"], lines, pretty=pretty, indent=indent,
                    depth=depth, in_stylesheet=True,
                )
            elif kind == "selector":
                self._emit_block(
                    [frag["compound"]], frag, lines,
                    pretty=pretty, indent=indent, depth=depth,
                )
            elif kind == "selectorList":
                if not frag["compounds"]:
                    raise ValueError(
                        "selectorList has no selector children; "
                        "add at least one .selector(...)",
                    )
                self._emit_block(
                    frag["compounds"], frag, lines,
                    pretty=pretty, indent=indent, depth=depth,
                    consume_selectors_as_list=True,
                )
        flush()

    # ------------------------------------------------------------------
    # Block emission (selector or selectorList)
    # ------------------------------------------------------------------

    def _emit_block(
        self,
        selector_strings: list[str],
        frag: dict[str, Any],
        lines: list[str],
        *,
        pretty: bool,
        indent: str,
        depth: int,
        consume_selectors_as_list: bool = False,
    ) -> None:
        """Emit a ``selectors { body }`` block from a selector fragment.

        Body = the fragment's rule(s), cssvar(s) and nested selector(s).
        Rules are grouped by ``(media, supports)``: the base group is
        inlined, the others become nested ``@media`` / ``@supports``.
        """
        selectorList = ", ".join(selector_strings)
        outer = indent * depth if pretty else ""
        inner = indent * (depth + 1) if pretty else ""

        body_frags = frag["body"]
        rule_groups = self._group_rules(body_frags)
        base_properties = rule_groups.pop((None, None), [])
        cssvar_lines = self._cssvar_lines(body_frags)
        nested_selectors = (
            [] if consume_selectors_as_list
            else [f for f in body_frags if f["kind"] == "selector"]
        )

        body = base_properties + cssvar_lines
        comment = self._comment_spec(frag.get("comment"))
        if comment.position == "block" and comment.text:
            lines.append(f"{outer}/* {comment.text} */")
        inline = comment.text if comment.position == "inline" else None
        if inline is not None and body:
            body[-1] = f"{body[-1]} /* {inline} */"
        elif inline is not None and not body and not nested_selectors and not rule_groups:
            body = [f"/* {inline} */"]

        if pretty:
            lines.append(f"{outer}{selectorList} {{")
            for entry in body:
                lines.append(f"{inner}{entry}")
            for nested in nested_selectors:
                self._emit_block(
                    [nested["compound"]], nested, lines,
                    pretty=pretty, indent=indent, depth=depth + 1,
                )
            for (media, supports), properties in rule_groups.items():
                self._emit_at_group(
                    media, supports, selector_strings, properties, lines,
                    pretty=pretty, indent=indent, depth=depth + 1,
                )
            lines.append(f"{outer}}}")
        else:
            extras: list[str] = []
            for nested in nested_selectors:
                flat: list[str] = []
                self._emit_block(
                    [nested["compound"]], nested, flat,
                    pretty=False, indent=indent, depth=0,
                )
                extras.append(" ".join(flat))
            for (media, supports), properties in rule_groups.items():
                flat = []
                self._emit_at_group(
                    media, supports, selector_strings, properties, flat,
                    pretty=False, indent=indent, depth=0,
                )
                extras.append(" ".join(flat))
            body_text = " ".join(body)
            combined = " ".join(part for part in (body_text, *extras) if part)
            lines.append(f"{selectorList} {{ {combined} }}")

    def _emit_at_group(
        self,
        media: str | None,
        supports: str | None,
        parent_selectors: list[str],
        properties: list[str],
        lines: list[str],
        *,
        pretty: bool,
        indent: str,
        depth: int,
    ) -> None:
        """Emit a ``@media``/``@supports`` block re-using the parent selector.

        When both are present, ``@supports`` wraps ``@media``.
        """
        parent_selector_list = ", ".join(parent_selectors)
        if pretty:
            current_depth = depth
            outer = indent * current_depth
            if supports is not None:
                lines.append(f"{outer}@supports {supports} {{")
                current_depth += 1
                outer = indent * current_depth
            if media is not None:
                lines.append(f"{outer}@media {media} {{")
                current_depth += 1
                outer = indent * current_depth
            lines.append(f"{outer}{parent_selector_list} {{")
            inner = indent * (current_depth + 1)
            for entry in properties:
                lines.append(f"{inner}{entry}")
            lines.append(f"{outer}}}")
            if media is not None:
                current_depth -= 1
                lines.append(f"{indent * current_depth}}}")
            if supports is not None:
                current_depth -= 1
                lines.append(f"{indent * current_depth}}}")
        else:
            inner_props = " ".join(properties)
            payload = f"{parent_selector_list} {{ {inner_props} }}"
            if media is not None:
                payload = f"@media {media} {{ {payload} }}"
            if supports is not None:
                payload = f"@supports {supports} {{ {payload} }}"
            lines.append(payload)

    # ------------------------------------------------------------------
    # Rule grouping / cssvars / imports / comments (on dict fragments)
    # ------------------------------------------------------------------

    def _group_rules(
        self, body_frags: list[dict[str, Any]],
    ) -> dict[tuple[str | None, str | None], list[str]]:
        """Group rule fragments by ``(media, supports)``, preserving order."""
        groups: dict[tuple[str | None, str | None], list[str]] = {}
        for frag in body_frags:
            if frag["kind"] != "rule":
                continue
            key = (frag["media"], frag["supports"])
            groups.setdefault(key, []).extend(frag["props"])
        return groups

    def _cssvar_lines(self, body_frags: list[dict[str, Any]]) -> list[str]:
        """Declaration lines for the ``cssvar`` fragments in a block body."""
        result: list[str] = []
        for frag in body_frags:
            if frag["kind"] == "cssvar":
                result.extend(self._cssvar_decl(frag))
        return result

    def _cssvar_decl(self, frag: dict[str, Any]) -> list[str]:
        """One ``--name: value;`` declaration (with optional comment)."""
        declaration = f'--{frag["name"]}: {frag["value"]};'
        comment = frag.get("comment")
        if comment is None:
            return [declaration]
        text = str(comment)
        if len(text) <= COMMENT_INLINE_MAX_LEN:
            return [f"{declaration} /* {text} */"]
        return [f"/* {text} */", declaration]

    def _emit_root_cssvars(
        self,
        cssvars: list[dict[str, Any]],
        lines: list[str],
        *,
        pretty: bool,
        indent: str,
        depth: int,
    ) -> None:
        """Emit cssvar fragments as a single ``:root { ... }`` block."""
        body: list[str] = []
        for frag in cssvars:
            body.extend(self._cssvar_decl(frag))
        if not body:
            return
        outer = indent * depth if pretty else ""
        inner = indent * (depth + 1) if pretty else ""
        if pretty:
            lines.append(f"{outer}:root {{")
            for entry in body:
                lines.append(f"{inner}{entry}")
            lines.append(f"{outer}}}")
        else:
            lines.append(":root { " + " ".join(body) + " }")

    def _emit_import(
        self,
        frag: dict[str, Any],
        lines: list[str],
        *,
        pretty: bool,
        indent: str,
        depth: int,
    ) -> None:
        """Emit a single ``@import`` directive from an importcss fragment.

        Spec order: ``@import <url> <layer>? <supports>? <media-query-list>?;``.
        """
        url = frag["url"]
        if url is None:
            raise ValueError("importcss: missing required kwarg 'url'")
        layer = frag["layer"]
        supports = frag["supports"]
        media = frag["media"]

        parts: list[str] = [f'@import url("{url}")']
        if layer is not None:
            parts.append(f"layer({layer})" if layer != "" else "layer")
        if supports is not None:
            # ``supports`` is passed verbatim including its outer parens,
            # mirroring ``rule(supports="(...)")``: the spec syntax is
            # ``supports(<condition>)`` and the condition carries its own
            # parens, so we only prepend the keyword.
            parts.append(f"supports{supports}")
        if media is not None:
            parts.append(str(media))
        directive = " ".join(parts) + ";"

        outer = indent * depth if pretty else ""
        comment = frag.get("comment")
        if comment is not None:
            text = str(comment)
            if len(text) <= COMMENT_INLINE_MAX_LEN:
                lines.append(f"{outer}{directive} /* {text} */")
                return
            lines.append(f"{outer}/* {text} */")
        lines.append(f"{outer}{directive}")

    def _comment_spec(self, text: Any) -> _CommentSpec:
        """Classify a comment string as inline (<=60) or block."""
        if text is None:
            return _CommentSpec(text=None, position="inline")
        s = str(text)
        if len(s) <= COMMENT_INLINE_MAX_LEN:
            return _CommentSpec(text=s, position="inline")
        return _CommentSpec(text=s, position="block")


class _CommentSpec:
    """Tiny holder for comment text + inline/block position."""

    __slots__ = ("text", "position")

    def __init__(self, *, text: str | None, position: str) -> None:
        self.text = text
        self.position = position
