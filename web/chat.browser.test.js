// Packaged UI with synthetic APIs. No live credentials, projects or model calls.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const assets = path.resolve("src/tin_lite/static");

async function chatFixture(t, width = 1440) {
  const project = {id: "chat-project", name: "Chat project", workspace_id: "workspace", workspace_name: "Workspace", member_count: 1};
  const run = {id: "chat-run", workflow_name: "project.memory", status: "running"};
  const messages = Array.from({length: 12}, (_, index) => ({
    role: index % 2 ? "assistant" : "user",
    content: index % 2 ? `Reply ${index}. ${"Here is the project update. ".repeat(50)}` : `Question ${index}`,
    created_at: "2026-09-16T12:00:00Z",
    request_id: `request-${index}`,
    run_id: index === 11 ? run.id : null,
  }));
  let onSend;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = value => {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify(value));
    };
    if (url.pathname === "/") {
      response.setHeader("Content-Type", "text/html");
      return response.end((await fs.readFile(path.join(assets, "index.html"), "utf8"))
        .replaceAll("{{ASSET_VERSION}}", "test").replaceAll("{{CLERK_PUBLISHABLE_KEY}}", ""));
    }
    if (url.pathname.startsWith("/assets/")) {
      const file = path.join(assets, url.pathname.slice(8));
      try {
        const body = await fs.readFile(file);
        response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "application/octet-stream");
        return response.end(body);
      } catch { response.writeHead(404).end(); return; }
    }
    if (url.pathname === "/api/chat" && request.method === "POST") {
      let raw = "";
      for await (const chunk of request) raw += chunk;
      const body = JSON.parse(raw);
      onSend({body, reply(message = "Done.", status = 200) {
        response.statusCode = status;
        send(status === 200 ? {message, request_id: body.request_id, run: null} : {detail: message});
      }});
      return;
    }
    if (url.pathname === "/api/projects") return send([project]);
    if (url.pathname.endsWith("/chat/messages")) return send(messages);
    if (url.pathname.endsWith("/runs")) return send([run]);
    if (url.pathname.endsWith("/system")) return send({workflow_count: 0, running_count: run.status === "running" ? 1 : 0, waiting_count: 0, runs_this_month: 1});
    if (url.pathname.startsWith("/api/")) return send([]);
    response.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true});
  t.after(() => browser.close());
  const context = await browser.newContext({viewport: {width, height: 900}});
  await context.route("**/*", route => route.request().url().startsWith(base) ? route.continue() : route.abort());
  await context.addInitScript(() => {
    window.Clerk = {load: async () => {}, isSignedIn: true, user: {id: "member", firstName: "QA"}, session: {getToken: async () => "synthetic"}};
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.goto(`${base}/#chat`);
  const field = page.locator("#message");
  const thread = page.locator("#chat-thread");
  await field.waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => {
    const node = document.querySelector("#chat-thread");
    return node.scrollHeight - node.clientHeight - node.scrollTop <= 2;
  });
  return {
    page, field, thread, run,
    async submit(message, click = false) {
      const pending = new Promise(resolve => { onSend = resolve; });
      await field.fill(message);
      if (click) await page.getByRole("button", {name: "Send message", exact: true}).click();
      else await field.press("Enter");
      const request = await pending;
      assert.equal(await field.inputValue(), "", "composer clears before the response");
      assert.equal(await page.getByRole("button", {name: "Send message", exact: true}).isDisabled(), true);
      assert.equal(request.body.message, message.trim());
      assert.equal(request.body.project_id, project.id);
      assert.match(request.body.request_id, /^[0-9a-f-]{36}$/);
      return request;
    },
    async settled() {
      await page.locator("#chat-form .send-button:not(:disabled)").waitFor();
    },
  };
}

const scrollPosition = thread => thread.evaluate(node => ({top: node.scrollTop, bottom: node.scrollHeight - node.clientHeight - node.scrollTop}));

for (const width of [1440, 390]) test(`chat composer has only working controls at ${width}px`, async t => {
  const chat = await chatFixture(t, width);
  for (const theme of ["light", "dark"]) {
    await chat.page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    assert.equal(await chat.page.locator("#chat-form .attach-button").count(), 0);
    assert.equal(await chat.page.locator("#chat-form button").count(), 1);
    assert.equal(await chat.page.getByRole("button", {name: "Send message", exact: true}).isEnabled(), true);
    const layout = await chat.field.evaluate(field => {
      const form = field.form;
      const box = form.getBoundingClientRect();
      const input = field.getBoundingClientRect();
      return {
        first: form.firstElementChild === field,
        left: input.left - box.left,
        padding: parseFloat(getComputedStyle(form).paddingLeft),
        overflow: form.scrollWidth - form.clientWidth,
      };
    });
    assert.equal(layout.first, true, "no empty attachment slot before the message");
    assert.ok(Math.abs(layout.left - layout.padding) < 1, "message starts at the composer padding");
    assert.ok(layout.overflow <= 1, "composer fits without horizontal overflow");
    if (process.env.TIN_CHAT_COMPOSER_SCREENSHOTS) {
      await fs.mkdir(process.env.TIN_CHAT_COMPOSER_SCREENSHOTS, {recursive: true});
      await chat.page.locator("#chat-form").screenshot({
        path: path.join(process.env.TIN_CHAT_COMPOSER_SCREENSHOTS, `composer-${theme}-${width}.png`),
      });
    }
  }
  await chat.field.focus();
  await chat.field.press("Tab");
  assert.equal(await chat.page.locator(".send-button").evaluate(button => button === document.activeElement), true);
});

for (const width of [1440, 390]) test(`chat clears on send and preserves reading position at ${width}px`, async t => {
  const chat = await chatFixture(t, width);
  assert.ok((await scrollPosition(chat.thread)).bottom <= 2, "history opens at the latest message");
  await chat.thread.hover();
  await chat.page.mouse.wheel(0, -500);
  await chat.page.waitForFunction(() => {
    const node = document.querySelector("#chat-thread");
    return node.scrollHeight - node.clientHeight - node.scrollTop > 400;
  });
  const reading = await scrollPosition(chat.thread);
  chat.run.status = "succeeded";
  await chat.thread.locator(".run-receipt code").filter({hasText: "succeeded"}).waitFor();
  // Catch the old CSS-smooth scroll even after the refresh has rendered.
  await chat.page.waitForTimeout(750);
  assert.ok(Math.abs((await scrollPosition(chat.thread)).top - reading.top) <= 2, "background refresh preserves reading position");

  const draft = "  Where were we?\nHow is my project going?  ";
  const request = await chat.submit(draft, true);
  assert.ok((await scrollPosition(chat.thread)).bottom <= 2, "sending reveals the submitted message");
  assert.ok(await chat.field.evaluate(node => node.clientHeight < 80), "cleared composer shrinks");
  await chat.thread.evaluate(node => node.scrollTo({top: 160, behavior: "instant"}));
  // Even identical text newly typed while waiting belongs to the next draft.
  await chat.field.fill(draft);
  const waitingPosition = await scrollPosition(chat.thread);
  request.reply("A long project update. ".repeat(160));
  await chat.settled();
  assert.equal(await chat.field.inputValue(), draft);
  assert.ok(Math.abs((await scrollPosition(chat.thread)).top - waitingPosition.top) <= 2, "arriving reply preserves reading position");
  chat.run.status = "failed";
  await chat.thread.locator(".run-receipt code").filter({hasText: "failed"}).waitFor();
  assert.ok(Math.abs((await scrollPosition(chat.thread)).top - waitingPosition.top) <= 2, "later polling does not pull the reader down");

  const next = await chat.submit("Continue");
  next.reply("Another long answer. ".repeat(160));
  await chat.settled();
  assert.ok((await scrollPosition(chat.thread)).bottom <= 2, "replies follow when already at the bottom");
});

test("chat failures restore the submitted draft without overwriting newer text", async t => {
  const chat = await chatFixture(t);
  const draft = "  Please summarize\nmy project.  ";
  const failed = await chat.submit(draft);
  failed.reply("Please try again", 503);
  await chat.settled();
  assert.equal(await chat.field.inputValue(), draft);
  const second = await chat.submit(draft);
  await chat.field.fill("A new draft");
  second.reply("Please try again", 503);
  await chat.settled();
  assert.equal(await chat.field.inputValue(), "A new draft");
  await chat.page.locator('[data-view="workflows"]').click();
  await chat.page.locator('[data-view="chat"]').click();
  assert.equal(await chat.field.inputValue(), "A new draft");
});

test("a delayed chat reply leaves the current view in place", async t => {
  const chat = await chatFixture(t);
  const request = await chat.submit("Project update");
  await chat.page.locator('[data-view="workflows"]').click();
  const response = chat.page.waitForResponse(url => new URL(url.url()).pathname === "/api/chat");
  request.reply("Your project update is ready.");
  await response;
  await chat.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await chat.page.locator(".system-view").count(), 1);
  assert.equal(new URL(chat.page.url()).pathname, "/system");
  await chat.page.locator('[data-view="chat"]').click();
  await chat.thread.getByText("Your project update is ready.", {exact: true}).waitFor();
  assert.equal(await chat.field.inputValue(), "");
});
