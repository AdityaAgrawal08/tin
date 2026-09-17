import { build } from "esbuild";
import { copyFile } from "node:fs/promises";
await build({
  entryPoints: ["web/diagram-renderer.js"],
  bundle: true,
  format: "iife",
  globalName: "TinDiagramBundle",
  minifyWhitespace: true,
  minifyIdentifiers: true,
  outfile: "src/tin_lite/static/diagram-renderer.js",
  define: { "import.meta.url": "undefined" },
});
await copyFile(
  "node_modules/libavoid-js/dist/libavoid.wasm",
  "src/tin_lite/static/diagram-routing.wasm",
);
