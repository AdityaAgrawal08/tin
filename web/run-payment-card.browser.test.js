import assert from "node:assert/strict";
import test from "node:test";
import {chromium} from "playwright";

async function harness() {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage();
  await page.route("**/*", route => route.fulfill({contentType:"text/html", body:"<!doctype html><title>Card form test</title>"}));
  await page.goto("https://example.test");
  await page.addScriptTag({path:"src/tin_lite/static/run-payment-card.js"});
  return {page, close:() => browser.close()};
}

async function start(page, path="/api/workflows/qa/runs") {
  await page.evaluate(path => {
    window.finished = false;
    window.TinRunPaymentCard.prepare(path, {
      method:"POST", body:JSON.stringify({project_id:"project", inputs:{product_url:"https://example.test"}}),
    }, {
      workflows:[{id:"qa", key:"qa.signup_walkthrough"}],
      projectWorkflows:[{id:"saved", workflow_id:"qa"}],
      assertContext() { if(window.changedProject) throw new Error("Project changed"); },
    }).then(value => {window.result=value;}, error => {window.error=error.message;})
      .finally(() => {window.finished=true;});
  }, path);
}

test("card is optional; saving a configuration never prompts for one", async () => {
  const f=await harness();
  try {
    await start(f.page, "/api/projects/project/workflows");
    await f.page.waitForFunction(() => window.finished);
    assert.equal(await f.page.locator("dialog").count(), 0);
    await start(f.page);
    assert.equal(await f.page.getByRole("group").isVisible(), false);
    await f.page.getByRole("button", {name:"Start walkthrough"}).click();
    await f.page.waitForFunction(() => window.finished);
    const body=await f.page.evaluate(() => JSON.parse(window.result.body));
    assert.equal(body.payment_card, undefined);
    assert.equal(await f.page.locator("dialog").count(), 0);
  } finally {await f.close();}
});

test("saved workflow starts collect a new card outside saved inputs and clear the form", async () => {
  const f=await harness();
  try {
    await start(f.page, "/api/projects/project/workflows/saved/runs");
    await f.page.getByLabel("Add a card for this run").check();
    await f.page.getByLabel("Card number", {exact:true}).fill("4242424242424242");
    await f.page.getByLabel("Name on card").fill("Example Tester");
    await f.page.getByLabel("Expiry (MM/YY)").fill("12/39");
    await f.page.getByLabel("Security code").fill("987");
    await f.page.getByLabel("Billing address").fill("123 Example Street, Test City");
    await f.page.getByRole("button", {name:"Start walkthrough"}).click();
    await f.page.waitForFunction(() => window.finished);
    const body=await f.page.evaluate(() => JSON.parse(window.result.body));
    assert.equal(body.payment_card.number, "4242424242424242");
    assert.deepEqual(body.inputs, {product_url:"https://example.test"});
    assert.equal(await f.page.locator("dialog, input[type=password]").count(), 0);
    assert.equal(await f.page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    await start(f.page, "/api/projects/project/workflows/saved/runs");
    assert.equal(await f.page.getByLabel("Add a card for this run").isChecked(), false);
    await f.page.getByRole("button", {name:"Cancel", exact:true}).click();
    await f.page.waitForFunction(() => window.finished);
    assert.equal(await f.page.evaluate(() => window.error), "Run cancelled.");
  } finally {await f.close();}
});

test("changing project while the dialog is open prevents the start", async () => {
  const f=await harness();
  try {
    await start(f.page);
    await f.page.evaluate(() => {window.changedProject=true;});
    await f.page.getByRole("button", {name:"Start walkthrough"}).click();
    await f.page.waitForFunction(() => window.finished);
    assert.equal(await f.page.evaluate(() => window.error), "Project changed");
    assert.equal(await f.page.locator("dialog").count(), 0);
  } finally {await f.close();}
});
