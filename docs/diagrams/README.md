# README diagrams

The `.mmd` files are the editable sources for the two figures in
[`README.md`](../../README.md). The architecture guide embeds these same SVGs so
its overview stays consistent with the README. Layout groups arrange the figures;
the visible E2B frame identifies where the agent and its browser execute.

The architecture overview distinguishes Tin's web app from the agent-controlled
Camoufox browser inside E2B. Temporal Cloud coordinates work; Tin's workers execute
workflow code and create sandboxes. Arrows show calls or work dispatch, not every
response or storage transfer. Sandbox results return to the trusted server for
validation and publication. Small text workflows execute in trusted activities and
do not create a sandbox. Model API keys and integration credentials remain on the
server; a brokered ChatGPT session or a run-bound grant is a separate auth mechanism.

The SVGs use the shared Tin renderer: FK Grotesk Neue, Geist Mono, Paper and Coal
colors, open arrowheads, and spacing between arrows and nodes. Steps, execution surfaces,
and storage share one neutral fill; storage keeps its cylinder shape. Review gates,
results, and enclosing groups retain their distinct treatments. These are documentation
exports for GitHub, which cannot run Tin's renderer. Product and project-state diagrams
continue to derive their SVG at read time.

Each figure has a light and dark export. The README uses GitHub's supported
[`picture` theme selection](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/quickstart-for-writing-on-github)
with a light fallback. The SVG canvas is transparent so the diagram blends with
GitHub's own background; node fills and label backgrounds retain the Tin palette.
The links beneath each figure open its source and SVG files directly on GitHub.
The standalone viewer source remains in [`viewer/`](viewer/), but the README does
not link to a hosted viewer.

The exporter measures text in Chromium using the packaged fonts, then converts glyphs
to vector paths. An SVG loaded as an image therefore needs no font download, font
installation, embedded font binary, script, or external resource. Text cannot be
selected in these exports; the README's alt text and linked Mermaid sources provide
text alternatives. Edit the sources and regenerate both themes together.

## Regenerate

Use the shared renderer at `52344467a4b6d9eed302207a560bc640e0f3ca0c` from
`codex/diagram-chain-alignment`. The README branch deliberately does not import that branch's
application changes. Node.js 22 or newer and `uv` are required.

From this checkout, create a separate, clean renderer checkout once:

```sh
git fetch origin codex/diagram-chain-alignment
git worktree add --detach ../tin-readme-renderer 52344467a4b6d9eed302207a560bc640e0f3ca0c
npm --prefix ../tin-readme-renderer ci
npm --prefix ../tin-readme-renderer run build:diagrams
```

Install the renderer checkout's Playwright Chromium if it is not already available:

```sh
cd ../tin-readme-renderer
npx playwright install chromium
```

Back in the README checkout, run:

```sh
node scripts/render_readme_diagrams.mjs ../tin-readme-renderer
```

The exporter uses `fonttools==4.59.0` and `brotli==1.1.0` in an isolated `uv`
environment. It audits node and label bounds, outlines text, rejects external SVG
dependencies, and checks light/dark image selection at 830 px and 390 px. Review
the screenshots in `/tmp/tin-readme-diagram-qa` (or set
`TIN_DIAGRAM_SCREENSHOTS`) before committing the source and four exports.
