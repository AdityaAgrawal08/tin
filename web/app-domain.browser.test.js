// Two local origins, packaged UI and synthetic Clerk/provider responses. No live accounts.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

test("domain move preserves reader auth, stable MCP and completed integration handoff", async () => {
  const assets = path.resolve("src/tin_lite/static");
  let appOrigin, oldOrigin;
  const calls = [], errors = [];
  const respond = isLegacy => async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    if (isLegacy && ["/", "/connect"].includes(url.pathname)) {
      response.writeHead(302, {Location: appOrigin + request.url}); return response.end();
    }
    if (url.pathname.startsWith("/assets/")) {
      const file = path.join(assets, url.pathname.slice(8));
      const body = await fs.readFile(file).catch(() => null);
      if (!body) return response.writeHead(404).end();
      response.writeHead(200, {"Content-Type": file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "application/octet-stream"});
      return response.end(body);
    }
    if (url.pathname === "/api/integrations/github/complete") {
      let body = ""; for await (const part of request) body += part;
      calls.push(JSON.parse(body));
      response.writeHead(200, {"Content-Type": "application/json"});
      return response.end(JSON.stringify({key: "infra.github", name: "GitHub", project_id: "project-1"}));
    }
    if (url.pathname.startsWith("/api/")) return response.writeHead(500).end();
    let html = await fs.readFile(path.join(assets, "index.html"), "utf8");
    const values = {ASSET_VERSION: "test", BILLING_ENABLED: "false", APP_URL: appOrigin, MCP_URL: oldOrigin + "/mcp", CLERK_PUBLISHABLE_KEY: "synthetic", CLERK_FRONTEND_API_URL: "https://clerk.test", AUTH_RETURN_URL: (url.searchParams.get("redirect_url") || "").replaceAll("&", "&amp;").replaceAll('"', "&quot;"), AUTH_FLOW: "product"};
    for (const [key, value] of Object.entries(values)) html = html.replaceAll(`{{${key}}}`, value);
    response.writeHead(200, {"Content-Type": "text/html"}); response.end(html);
  };
  const app = http.createServer(respond(false)), old = http.createServer(respond(true));
  await new Promise(resolve => app.listen(0, "127.0.0.1", resolve));
  await new Promise(resolve => old.listen(0, "127.0.0.1", resolve));
  appOrigin = `http://127.0.0.1:${app.address().port}`;
  oldOrigin = `http://127.0.0.1:${old.address().port}`;
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext();
    await context.route("**/*", route => [appOrigin, oldOrigin].some(origin => route.request().url().startsWith(origin)) ? route.continue() : route.abort());
    await context.addInitScript(oldOrigin => {
      window.Clerk = {
        isSignedIn: location.origin === oldOrigin && location.pathname.startsWith("/integrations/callback/"),
        user: {id: "user_fixture", firstName: "Fixture"},
        session: {getToken: async () => "synthetic"},
        load: async options => {window.loadOptions = options;},
        mountSignIn: (node, options) => {window.authOptions = options; node.textContent = "Sign in";},
        mountSignUp: (node, options) => {window.authOptions = options; node.textContent = "Sign up";},
      };
    }, oldOrigin);
    const page = await context.newPage(); page.on("pageerror", error => errors.push(error.message));
    const reader = "/?project=project-1#document/00000000-0000-0000-0000-000000000001?return=decisions";
    await page.goto(oldOrigin + reader);
    await page.locator("#clerk-auth").waitFor();
    const cleanReader = appOrigin + "/document/00000000-0000-0000-0000-000000000001?project=project-1&return=decisions";
    assert.equal(new URL(page.url()).pathname, "/sign-in");
    assert.equal(new URL(page.url()).hash, "");
    assert.equal(await page.evaluate(() => window.authOptions.forceRedirectUrl), cleanReader);
    assert.match(await page.evaluate(() => agentCommandFor("codex")), new RegExp(oldOrigin + "/mcp"));
    const signUp = await page.evaluate(() => window.authOptions.signUpUrl);
    await page.goto(appOrigin + signUp);
    await page.locator("#clerk-auth").waitFor();
    assert.equal(await page.evaluate(() => window.authOptions.forceRedirectUrl), cleanReader);
    await page.goto(oldOrigin + "/sign-in?invite=fixture");
    await page.locator("#clerk-auth").waitFor();
    assert.equal(await page.evaluate(() => window.authOptions.fallbackRedirectUrl), appOrigin + "/system?invite=fixture");
    assert.deepEqual(await page.evaluate(() => window.loadOptions.allowedRedirectOrigins), [appOrigin]);
    await page.goto(oldOrigin + "/integrations/callback/github?state=original-state&code=original-code");
    await page.waitForURL(url => url.origin === appOrigin);
    await page.locator("#clerk-auth").waitFor();
    const callbackTarget = new URL(page.url());
    assert.equal(callbackTarget.searchParams.get("project"), "project-1");
    assert.equal(callbackTarget.searchParams.get("connected_provider"), "infra.github");
    assert.equal(new URL(callbackTarget.searchParams.get("redirect_url")).pathname, "/integrations");
    assert.equal(callbackTarget.hash, "");
    assert.equal(callbackTarget.searchParams.has("code"), false);
    assert.equal(callbackTarget.searchParams.has("state"), false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].state, "original-state");
    assert.equal(calls[0].code, "original-code");
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await Promise.all([app, old].map(server => new Promise(resolve => server.close(resolve))));
  }
});
