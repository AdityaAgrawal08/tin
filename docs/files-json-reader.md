# Files JSON reader

The JSON reader reuses the product's typography, radii, text card, raw-view
switch and theme roles. No new color or font tokens are introduced.

`.json` files open as a plain DOM tree in a centered 760px card, with a fixed
18px disclosure gutter and two-character indentation on each text block. Keys
and scalar literals use `--ink`, strings use `--ink-secondary`, and punctuation,
carets and summaries use `--ink-muted`. The handoff's final instruction for
numbers, booleans and null takes precedence over its earlier contradictory
sentence. The card uses `--paper-card`, `--card-border`, and the existing 8px
radius. Type is 12.5/20 mono, becoming 11.5/18 on narrow screens.

The tree counts fully expanded lines once. At more than 400 lines, arrays fold
breadth first until at most 400 lines remain visible or there are no more arrays
to fold; objects stay open. A file containing only object members can therefore
remain longer than 400 lines. Disclosure buttons work with the keyboard and
retain focus after toggling. Extreme indentation is limited to 60% of the text
column so deeply nested data remains readable without sideways scrolling.

View mode and disclosure state belong to the current file opening. Switching
between raw and formatted preserves folds; leaving and reopening resets them.
The raw view and Copy preserve the original decoded UTF-8 text, including a BOM
and line endings. Download continues through the existing authenticated,
revision-pinned raw endpoint. Formatting never writes to project state.

Invalid JSON uses wrapped text and a factual note in the context bar, without a
mode switch. `.jsonl` remains plain text. All existing text fallback cards now
wrap. Markdown, CSV tables, diagrams and media keep their existing readers.

JSON previews use the existing **1,000,000-byte canonical text publication
limit** (`MAX_PROJECT_FILE_BYTES` / `_PUBLICATION_TEXT_MAX_BYTES`), rather than
the separate CSV reader's 2 MiB raw cache limit. Larger JSON files offer Download
raw only. The reader cancels oversized responses before parsing; for chunked
responses without a size it reports a lower bound instead of a guessed total.

Run `npm run test:json-viewer` for parser, disclosure, byte-preservation and
packaged-app browser checks. The browser tests cover formatted, raw, invalid,
folded, oversized and text-fallback states at 1440, 768 and 390 pixels in both
themes, including real clipboard and download checks with synthetic local
fixtures. Set `TIN_JSON_SCREENSHOTS_DIR` to save those screenshots.
