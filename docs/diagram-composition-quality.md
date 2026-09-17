# Diagram composition quality

Contributor reference for the renderer, checker images and `content.diagram` **2.1.0**.
It follows the designer reference without adding another layout engine or expanding the grammar.

## What changed

**Planning and inspection.** `content.diagram` advances to **2.1.0**. The skill asks the author
to establish the main sequence, real entry, actual terminal outcomes, equivalent branches,
and feedback from the brief and pinned evidence. Existing ordered groups and local directions
express that intent. A cycle need not have a terminal; unequal branches need not be symmetric.
The same controller still allows one initial candidate and at most two repairs, with real
light/dark images and acceptance bound to the exact source hash.

**Advisory diagnostics.** The offline checker measures actual painted SVG geometry: dimensions,
bends, crossings, short jogs, total path length, longest detour ratio, local chain-axis drift,
equivalent-branch imbalance, and fit scale in a fixed 1200×800 viewport. These accompany the
inspection images. They are not new publication thresholds or proof that a main path is clear.
Older reports without metrics still work. The checker and validator IDs remain
`tin-diagram-check.v1` and `tin-diagram.reviewed.v1`.

The independent publication validator accepts additive theme diagnostics while requiring
exactly one passing light proof and one passing dark proof, in order. Source and renderer
hashes, empty issue lists, and the overall passing result remain mandatory. Deployment
preflight caught the old exact-dictionary comparison rejecting these new advisory fields;
regression coverage exercises both report formats and malformed or failing theme proofs.

**Bounded placement.** The original three composition candidates still establish a valid
baseline. Three extra candidates try equivalent-peer centering, measured local compaction,
and their combination. Peer signatures include edge direction and kind. Centering uses the
visible band envelope, not equal center distances between unequal-sized cards. Children keep
their order and measured whitespace. Frame padding and lane headings remain protected.

Compaction stops reserving every distant return label in every intervening sibling gap. Labels
between adjacent regions still reserve their measured size, plus clearance; all gaps remain
at least 72px. The existing libavoid router and label placement revalidate every candidate.
An extra candidate is rejected if it adds crossings, short jogs, or local chain drift, adds
more than 5% route length, or reduces overview fit scale by more than 3%. Final ranking includes
the existing bend/length/area penalties plus axis-continuity and equivalent-branch preferences.
No node, edge, label, or group is removed to improve a metric. Maximum candidate count: six.

**Unchanged foundations.** Packaged Geist fonts and measured padding, shaded frames, 4.5×6px
open heads, matching opaque shafts, 6px source / 10px target gaps, SVG exports, and Files
fit/zoom/pan controls remain intact. Flat ELK layout, grammar, review gates, canonical `.mmd`
artifacts, and historic receipts retain their contracts.

## Before/after evidence

Compared **49 identical sources in both themes**, using the baseline's packaged renderer and
the new renderer against the same fonts and CSS. This includes all 41 existing candidates
(seven architecture studies, three Registry presentations, 28 varied flat fixtures, and three
composition regressions), seven new designer fixtures, and the saved ClawMessenger diagnostic.
Both sides have zero geometry audit issues. Source hashes and all node, edge, label, and named
group identities match. Theme geometry agrees. Seven layouts change; 42 keep their baseline.

| Candidate | Before | After |
| --- | --- | --- |
| Branching review chain | 5 bends; 1,708px of paths; 1,328px high | 2 bends; 1,172px of paths; 1,208px high |
| Workflow anatomy | 5 bends; 2,540px of paths; 1,676px wide | 4 bends; 1,892px of paths; 1,560px wide |
| LinkedIn sequence | 1,632px wide | 1,552px wide |
| Memory consolidation | 508.5px high | 468.5px high |
| Ongoing-loop fixture | 920px wide; 1,092px of paths | 632px wide; 516px of paths |
| Unequal peer branches, LR and RL | 96px total hub-to-band imbalance | 0px; same bends and path length |

Dimensions here include the portable export's 24px margin on each side. Checker diagnostics
use the SVG's unpadded internal viewport; do not mix the two sets of dimensions.
The three Registry presentations and the already-clean assembly/reference cases are preserved.
Visual review covers the seven original studies, changed arrangements, designer probes, and the
dense saved diagnostic, with natural-scale detail checks for padding, labels, and connectors.

Validation completed locally:

- 25 renderer/quality tests and the exact-source checker test pass.
- 576 browser geometry cases: 48 public fixtures × two themes × two widths × three surfaces.
- Both Files viewport suites pass, including fit on open, zoom/pan, touch, theme changes,
  camera persistence, and tall/wide diagrams. One positional fixture reference was replaced
  with its stable ID so extending the fixture bank cannot silently change the viewport test.
- Full backend invocation: **1,326 passed, 504 skipped** (integration services not configured),
  four existing warnings. The focused diagram subset is **41 passed, two skipped**.
- Ruff formatting/lint and import-boundary checks pass. Portable SVG font embedding, gallery
  theme/filter controls, comparison source/identity equality, and comparison fit/zoom pass.

Use the repository's Playwright harness for fixture-based visual checks. Rebuilt E2B
images and authenticated product interaction are separate verification steps; fixture
rendering alone does not prove either. Do not change customer artifacts to test the renderer.
Its 62 geometric crossings and roughly 0.28 internal fit scale are now visible diagnostics;
the safe local candidates do not solve its overall density. A future authoring pass should
reconsider its hierarchy using the new inspection guidance. No paid model run was performed.

## What we deliberately did not ship

An experiment with ELK's public
[edge straightness priority](https://eclipse.dev/elk/reference/options/org-eclipse-elk-layered-priority-straightness.html)
and [first/last layer constraints](https://eclipse.dev/elk/reference/options/org-eclipse-elk-layered-layering-layerConstraint.html)
did not produce a net improvement across the initial 41 cases or the lifecycle probe under
the geometry/legibility guards. That code was removed. The flat lifecycle and simple composed
lifecycle retain their original layouts. Compaction is a local improvement, not a global
rank/column optimizer, and the renderer still cannot infer a semantic main path in an ambiguous
state machine. Authored hierarchy and the inspection turn remain responsible for that judgment.

Shared trunks/junctions, a primary-path DSL, automatic branch preference, and a new graph engine
remain deferred. They would need separate evidence and grammar/semantic tests. Signals and
ordinary calls must never be merged into a misleading shared dependency.

## Reproduce and review

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build:diagrams
npm run review:diagrams -- /tmp/tin-diagrams-after
# Optional local .mmd candidates follow the output directory; never check private project
# source into this repository merely to build a visual regression gallery.
npm run review:diagrams -- /tmp/tin-diagrams-after /absolute/local/candidate.mmd
```

For the baseline, capture `app.css`, `diagram-renderer.js`, `diagram-routing.wasm`, and the four
diagram fonts from the baseline revision into a separate directory. Then run the same fixture
set with `TIN_DIAGRAM_REVIEW_ASSETS=/absolute/baseline-assets`. Only the developer gallery
supports this override; the publication checker always uses its fixed packaged allowlist.

```sh
node scripts/compare_diagrams.mjs /tmp/tin-diagrams-before /tmp/tin-diagrams-after /tmp/tin-diagram-comparison
python3 -m http.server 18865 --bind 127.0.0.1 --directory /tmp/tin-diagram-comparison
```

The comparison page has synchronized case/theme selection, fit/zoom controls, full SVG links,
and `comparison.json`. It fails if sources or text/connectivity change. It is a local engineering
review artifact, not a new product surface. Current local review: `http://127.0.0.1:18865/`.

## Rollout checklist

1. Review the branch and comparison gallery. Merge using current repository conventions.
2. Build/deploy the packaged browser renderer and rebuild the default and isolated diagram
   checker images. `sandbox/template.py` now copies `web/diagram-quality.js` alongside the
   checker; omitting it would break the Node import. The browser bundle embeds its own copy.
3. Verify actual packaged-image checks for both profiles, including the unprivileged author
   and independent publication validator. Keep the existing source-hash and renderer-fingerprint
   proofs; do not reuse local screenshots as publication evidence.
4. Publish/sync the new **2.1.0 immutable definition** only after those images are available.
   Existing pinned definitions and receipts are not rewritten. No database migration is required.
5. If desired, run a separately authorized short and dense live generation pilot to evaluate
   model adherence to the updated planning guidance. Local tests establish deterministic geometry
   and review-protocol behavior, not that a new model run will always choose the ideal composition.
