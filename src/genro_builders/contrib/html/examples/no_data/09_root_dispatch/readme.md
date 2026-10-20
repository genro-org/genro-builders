# 09 — Root dispatch

The grammar API works on the **root bag** exactly as it works on any
node. `main(self, root)` receives the source bag, and every element —
including a sub-builder boundary like `svg` — can be opened directly
on it.

## A sub-builder on the root

```python
class CustomPage(HtmlBuilder):
    def main(self, root):
        svg = root.svg(viewBox="0 0 100 100", width=120, height=120)
        svg.rect(x=10, y=10, width=80, height=80, fill="#3498db")
        svg.circle(cx=50, cy=50, r=25, fill="#e74c3c")
```

`root.svg(...)` switches the active dialect: from `<svg>` down the
grammar is the SVG builder's, so `svg.rect(...)` and `svg.circle(...)`
resolve against the SVG schema — the same behaviour you get with
`body.svg(...)` in `03_subbuilders`.

## Why this example exists

Element creation has two entry points — a node (`body.div(...)`) and
a bag (`root.div(...)`) — and both must apply the same grammar
semantics: sub-builder switch, data-element field mapping, `nodeId`
uniqueness. This page exercises the bag entry point on the sub-builder
case; it fails if the two paths ever diverge again.

Run it from this folder:

```bash
python root_dispatch.py
```
