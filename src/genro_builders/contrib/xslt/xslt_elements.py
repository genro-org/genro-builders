# Copyright 2025 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""XSLT 1.0 grammar (working subset) for genro-builders.

An XSLT stylesheet is XML, so it renders through the core ``XmlRenderer``
with no new renderer. Two element families share one tree:

- **XSLT instructions** (``xslt:template``, ``xslt:for-each``, ...). Each
  declares ``_meta={"render_tag": "xslt:<local>"}``: the Python method
  name stays a legal identifier (``for_each``) while the emitted tag is
  the prefixed name (``xslt:for-each``). This reuses the renderer's
  existing ``render_tag`` mechanism (the same one that turns the SVG
  ``html`` sub-builder into ``<foreignObject>``) — no XSLT-specific
  render code. The ``xslt`` prefix is declared once by the user as an
  ``xmlns_xslt`` attribute on the ``stylesheet`` root (emitted as
  ``xmlns:xslt``).

- **Literal result elements** — the output vocabulary copied verbatim.
  These come from the HTML5 grammar mixed into ``XsltBuilder``
  (``Html5Elements``), not declared here: in XSLT they are *part of the
  stylesheet grammar*, interleaved with the instructions at the same
  level. An XSLT instruction may nest inside any of them, which
  ``XsltBuilder.custom_require_sub_tag_validation`` allows.

Two instruction methods are renamed to avoid colliding with the HTML
tags of the same name: ``xslt_output``/``xslt_template`` (the emitted
tags stay ``xslt:output``/``xslt:template``, from ``render_tag``).

Attribute names like ``select``/``match``/``test`` are XPath and are
emitted verbatim. ``{...}`` attribute-value-templates pass through too
(only ``^``/``=`` introduce pointers; suffixes explicitly format them).
"""

from __future__ import annotations

from genro_builders.builder import element


class XsltElements:
    """Mixin: the XSLT instruction vocabulary (``xslt:*``)."""

    @element(sub_tags="*", _meta={"render_tag": "xslt:stylesheet"})
    def stylesheet(self, **kwargs):
        """Root of a stylesheet. Carries ``version`` and the namespace
        declaration ``xmlns_xslt`` (emitted as ``xmlns:xslt``)."""
        ...

    @element(_meta={"render_tag": "xslt:output"})
    def xslt_output(self, **kwargs):
        """Serialization options for the result tree (``method``,
        ``encoding``, ``indent``). Named ``xslt_output`` to leave the bare
        ``output`` for the HTML ``<output>`` tag."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:template"})
    def xslt_template(self, **kwargs):
        """A transformation rule, selected by ``match`` (pattern) or
        invoked by ``name``. Named ``xslt_template`` to leave the bare
        ``template`` for the HTML ``<template>`` tag."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:apply-templates"})
    def apply_templates(self, **kwargs):
        """Process the nodes chosen by ``select`` with their matching
        templates."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:call-template"})
    def call_template(self, **kwargs):
        """Invoke a named template (``name``)."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:param"})
    def param(self, **kwargs):
        """A template/stylesheet parameter (``name``, optional default
        via ``select`` or body)."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:with-param"})
    def with_param(self, **kwargs):
        """Pass an argument (``name``, ``select``) to a called template."""
        ...

    @element(_meta={"render_tag": "xslt:value-of"})
    def value_of(self, **kwargs):
        """Insert the string value of the XPath ``select`` into the
        output."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:for-each"})
    def for_each(self, **kwargs):
        """Iterate over the node-set chosen by ``select``."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:if"})
    def if_(self, **kwargs):
        """Conditional: emit the body when the XPath ``test`` is true.
        Named ``if_`` (``if`` is a Python keyword); the emitted tag is
        ``xslt:if`` from ``render_tag``, independent of the method name."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:choose"})
    def choose(self, **kwargs):
        """Multi-branch conditional: a series of ``when`` plus an
        optional ``otherwise``."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:when"})
    def when(self, **kwargs):
        """A branch of ``choose``, taken when its ``test`` is true."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:otherwise"})
    def otherwise(self, **kwargs):
        """The fallback branch of ``choose``."""
        ...

    @element(_meta={"render_tag": "xslt:text"})
    def text(self, **kwargs):
        """Literal text, with control over output escaping/whitespace."""
        ...

    @element(sub_tags="*", _meta={"render_tag": "xslt:variable"})
    def variable(self, **kwargs):
        """A named variable (``name``, value via ``select`` or body)."""
        ...
