// Fixture-only browser checks: no login, product API or private font fixture.
import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const origin = "https://app.tin.computer";
const assets = path.resolve("src/tin_lite/static");
const liveStylesheet = process.env.TIN_TEST_PRIVATE_FONTS_URL;

async function platformFont(page, selector) {
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument");
    const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
    const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
    return fonts.filter((font) => font.isCustomFont).map((font) => font.familyName);
  } finally { await cdp.detach(); }
}

test("optional brand fonts preserve offline defaults, auth typography and portable diagram faces", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const mode of ["default", "custom", "unavailable", "font-unavailable", ...(liveStylesheet ? ["live"] : [])]) {
      const page = await browser.newPage();
      const requests = [];
      const failed = [];
      page.on("requestfailed", (request) => failed.push(`${request.url()}: ${request.failure()?.errorText}`));
      const stylesheet = mode === "live" ? liveStylesheet : "https://fonts.example.test/brand.css";
      page.on("request", (request) => requests.push(request.url()));
      await page.route("**/*", async (route) => {
        const url = new URL(route.request().url());
        if (url.origin === origin && url.pathname === "/font-fixture") {
          return route.fulfill({ contentType: "text/html", body: `<!doctype html><html><head>
            <link rel="stylesheet" href="/assets/app.css"><link rel="stylesheet" href="/assets/auth.css">
            ${mode === "default" ? "" : `<link rel="stylesheet" href="${stylesheet}" crossorigin="anonymous">`}
            </head><body><p id="shell">Tin workflows</p><div class="auth-root"><p id="auth">Sign in to Tin</p></div>
            <p id="diagram" style="font-family:var(--diagram-sans)">A portable diagram</p></body></html>` });
        }
        if (url.origin === origin && url.pathname.startsWith("/assets/")) {
          return route.fulfill({ path: path.join(assets, url.pathname.slice(8)) });
        }
        if (mode === "custom" && url.href === stylesheet) {
          // An OFL face stands in for any operator-supplied brand font in CI.
          return route.fulfill({ contentType: "text/css", headers: { "Access-Control-Allow-Origin": origin },
            body: ':root { --brand-sans: "Geist Mono", monospace; }' });
        }
        if (mode === "font-unavailable" && url.href === stylesheet) {
          return route.fulfill({ contentType: "text/css", headers: { "Access-Control-Allow-Origin": origin },
            body: '@font-face{font-family:"Unavailable";src:url("https://fonts.example.test/missing.woff2")} :root{--brand-sans:"Unavailable","Geist Sans",sans-serif}' });
        }
        if (mode === "live" && url.origin === new URL(liveStylesheet).origin) return route.continue();
        return route.abort();
      });
      await page.goto(`${origin}/font-fixture`);
      await page.evaluate(async () => { await document.fonts.ready; });
      const expected = mode === "custom" ? "Geist Mono" : mode === "live" ? "FK Grotesk Neue" : "Geist";
      for (const selector of ["#shell", "#auth"]) {
        const fonts = await platformFont(page, selector);
        assert.ok(fonts.some((font) => font === expected), `${mode}/${selector}: actual fonts ${fonts}; failed requests: ${failed.join("; ")}`);
      }
      assert.deepEqual(await platformFont(page, "#diagram"), ["Geist"], "diagrams stay independent of hosted font");
      if (mode === "default") assert.ok(requests.every((url) => url.startsWith(origin)), "self-host defaults make no font-CDN request");
      await page.close();
    }
  } finally { await browser.close(); }
});
