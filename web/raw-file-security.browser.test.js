// Real Tin routes + Clerk verification; ephemeral signing key and synthetic project only.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs/promises";
import readline from "node:readline";
import test from "node:test";
import { chromium } from "playwright";

test("untrusted project files cannot inherit Tin privileges", { timeout: 90000 }, async (t) => {
  const server = spawn(".venv/bin/python", ["tests/raw_file_security_fixture.py"], { stdio: ["ignore", "pipe", "pipe"] });
  let errors = "";
  server.stderr.on("data", (chunk) => { errors += chunk; });
  server.on("exit", (code, signal) => { if (code) console.error(`Fixture exit ${code}/${signal}: ${errors}`); });
  t.after(async () => {
    if (server.exitCode === null) {
      const ended = once(server, "exit");
      server.kill("SIGTERM");
      await ended;
    }
  });
  const lines = readline.createInterface({ input: server.stdout });
  const [line] = await Promise.race([
    once(lines, "line"),
    once(server, "exit").then(() => { throw new Error(`Fixture exited: ${errors}`); }),
  ]);
  const { origin, project, revision, runs } = JSON.parse(line);
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const context = await browser.newContext({ acceptDownloads: true });
  // Wait for the local server to accept connections, then install a signed cookie.
  let session;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { session = await context.request.get(`${origin}/__test/session`); break; }
    catch { await new Promise((resolve) => setTimeout(resolve, 30)); }
  }
  assert.ok(session?.ok(), errors);
  const token = await session.text();
  await context.addInitScript((token) => {
    window.Clerk = { load: async () => {}, isSignedIn: true, user: { id: "user_Synthetic", firstName: "Fixture" }, session: { getToken: async () => token } };
  }, token);
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    // Unrelated dashboard projections are mocked. Files, documents, artifacts,
    // project listing and the victim endpoint use real authentication/routes.
    if (url.pathname.startsWith("/api/") && !url.pathname.includes("/files") && !url.pathname.includes("/artifact") && url.pathname !== "/api/projects") {
      return route.fulfill({ json: url.pathname.endsWith("/system")
        ? { waiting_count: 0, running_count: 0, workflow_count: 0 } : [] });
    }
    return route.continue();
  });
  async function check(name, run) { await run(); t.diagnostic(name); }
  const page = await context.newPage();
  const raw = (name) => `${origin}/api/projects/${project}/files/raw?${new URLSearchParams({ path: name, revision })}`;
  const artifact = (name, retained = false) => `${origin}/api/workflows/runs/${runs[name]}/artifact${retained ? "?source=retained" : ""}`;
  const stats = async () => (await context.request.get(`${origin}/__test/stats`)).json();

  await check("positive control steals synthetic private data through the ambient session", async () => {
    await page.goto(`${origin}/__test/unsafe`);
    await page.waitForFunction(async () => (await (await fetch("/__test/stats")).json()).length === 1);
    assert.deepEqual(await stats(), ["synthetic-other-project-secret"]);
    await context.request.post(`${origin}/__test/reset`);
  });

  await check("direct HTML/SVG/XML and retained artifacts download with exact original bytes", async () => {
    await page.goto(`${origin}/`);
    for (const name of ["attack.html", "attack.SVG", "attack.xhtml", "attack.xml", "unknown.bin"]) {
      for (const url of [raw(name), artifact(name), ...(name === "attack.SVG" ? [artifact(name, true)] : [])]) {
        const original = await context.request.get(url);
        assert.equal(original.status(), 200);
        const downloading = page.waitForEvent("download");
        await page.evaluate((url) => {
          const link = document.createElement("a"); link.href = url; document.body.append(link); link.click(); link.remove();
        }, url);
        const download = await downloading;
        assert.equal(download.suggestedFilename(), name);
        assert.deepEqual(await fs.readFile(await download.path()), await original.body());
        assert.equal(await page.evaluate(() => window.attackExecuted), undefined);
      }
    }
    assert.deepEqual(await stats(), []);
  });

  await check("the HTTP sandbox also blocks scripts if a client displays the document inline", async () => {
    for (const url of [raw("attack.html"), raw("attack.SVG"), artifact("attack.SVG", true)]) {
      // Change only disposition; the policy under test comes from the actual API.
      await page.route(url, async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, headers: { ...response.headers(), "content-disposition": "inline" } });
      });
      await page.goto(url);
      assert.equal(await page.evaluate(() => window.attackExecuted), undefined);
      assert.equal(await page.evaluate(() => window.origin), "null");
      await page.unroute(url);
    }
    assert.deepEqual(await stats(), []);
  });

  await page.goto(`${origin}/#files`);
  await page.locator(".files-view").waitFor();
  async function open(name) {
    await page.evaluate(({ name, revision }) => goToRoute(`file?${new URLSearchParams({ path: name, revision })}`), { name, revision });
    await page.waitForFunction((name) => document.querySelector(".project-file-path")?.textContent === name, name);
  }

  await check("raw Blob views are plain text even when the response is HTML or SVG", async () => {
    for (const name of ["attack.html", "attack.SVG", "notes.md"]) {
      const popup = context.waitForEvent("page");
      await page.evaluate(({ name, revision }) => downloadProjectFile({ path: name, revision }, true), { name, revision });
      const view = await popup;
      await view.waitForLoadState();
      assert.equal(await view.evaluate(() => document.contentType), "text/plain");
      assert.equal(await view.evaluate(() => window.attackExecuted), undefined);
      assert.equal(await view.locator("pre").textContent(), await (await context.request.get(raw(name))).text());
      await view.close();
    }
    assert.deepEqual(await stats(), []);
  });

  await check("SVG and raster image previews work; SVG document navigation has no Tin origin", async () => {
    for (const name of ["safe.png", "attack.SVG"]) {
      await open(name);
      const img = page.locator(".project-media-image");
      await img.evaluate((image) => image.decode());
      assert.ok(await img.evaluate((image) => image.naturalWidth > 0));
      const src = await img.getAttribute("src");
      if (name.endsWith("SVG")) {
        assert.ok(src.startsWith("data:image/svg+xml;base64,"));
        // Emulate opening the image as a document. Its scripts may execute there,
        // but it must have an opaque origin and cannot read the Tin session/data.
        const imagePage = await context.newPage();
        await imagePage.goto(src);
        assert.equal(await imagePage.evaluate(() => window.origin), "null");
        assert.equal(await imagePage.evaluate(() => {
          try { return document.cookie; } catch { return "blocked"; }
        }), "blocked");
        await imagePage.waitForTimeout(150);
        assert.deepEqual(await stats(), []);
        await imagePage.close();
      }
      const downloading = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download", exact: true }).click();
      const download = await downloading;
      assert.equal(download.suggestedFilename(), name);
      assert.deepEqual(await fs.readFile(await download.path()), await (await context.request.get(raw(name))).body());
    }
    // A misleading extension must not let a Blob URL sniff back into active SVG.
    await open("disguised.png");
    const disguised = await page.locator(".project-media-image").getAttribute("src");
    const imagePage = await context.newPage();
    await imagePage.goto(disguised);
    assert.equal(await imagePage.evaluate(() => window.attackExecuted), undefined);
    await imagePage.close();
    assert.deepEqual(await stats(), []);
  });
});
