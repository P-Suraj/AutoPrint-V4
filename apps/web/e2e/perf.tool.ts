// Load measurements on the production build (`vite preview`, which compresses and sends the host's headers).
//   E2E_TOOL=perf   through the same stack as the tests, but with the preview server instead of the dev server.
// For each first screen: what is downloaded, then first paint and the time until the screen can be used on a slow
// phone (about slow 3G: 400 ms delay, 400 kbit/s; processor four times slower), layout shift and long tasks.
// Chromium only: the throttling goes through its debugging protocol.
import { expect, test, type Browser, type Page } from "@playwright/test";
import { PDF, SHOP } from "./fixtures";

const SLOW = { offline: false, latency: 400, downloadThroughput: (400 * 1024) / 8, uploadThroughput: (400 * 1024) / 8 };

/** Records layout shifts and long tasks from the first moment of the page. */
const watch = () => {
  const w = window as unknown as { __m: { cls: number; shifts: string[]; long: number[] } };
  w.__m = { cls: 0, shifts: [], long: [] };
  new PerformanceObserver((list) => {
    for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean; sources?: { node?: Node }[] })[]) {
      if (e.hadRecentInput) continue;
      w.__m.cls += e.value;
      w.__m.shifts.push(`${e.value.toFixed(4)} at ${Math.round(e.startTime)} ms: ${(e.sources ?? []).map((s) => (s.node instanceof Element ? `${s.node.tagName.toLowerCase()}.${s.node.className}` : "?")).join(", ")}`);
    }
  }).observe({ type: "layout-shift", buffered: true });
  new PerformanceObserver((list) => { for (const e of list.getEntries()) w.__m.long.push(Math.round(e.duration)); }).observe({ type: "longtask", buffered: true });
};
const read = (page: Page) => page.evaluate(() => {
  const m = (window as unknown as { __m: { cls: number; shifts: string[]; long: number[] } }).__m;
  const paint = (name: string) => Math.round(performance.getEntriesByName(name)[0]?.startTime ?? -1);
  return { firstPaint: paint("first-paint"), firstContentfulPaint: paint("first-contentful-paint"), layoutShift: Number(m.cls.toFixed(4)), shifts: m.shifts, longTasks: m.long };
});

async function open(browser: Browser, slow: boolean) {
  const ctx = await browser.newContext({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.addInitScript(watch);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  const sizes = new Map<string, number>(), urls = new Map<string, string>();
  cdp.on("Network.responseReceived", (e) => urls.set(e.requestId, new URL(e.response.url).pathname));
  cdp.on("Network.loadingFinished", (e) => sizes.set(urls.get(e.requestId) ?? "?", Math.round(e.encodedDataLength)));
  if (slow) { await cdp.send("Network.emulateNetworkConditions", SLOW); await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 }); }
  return { ctx, page, sizes };
}
const kb = (n: number) => `${(n / 1024).toFixed(1)} KB`;
const total = (sizes: Map<string, number>) => kb([...sizes.values()].reduce((a, b) => a + b, 0));

for (const [name, path, ready] of [["home", "/", "Print from your phone"], ["shop page", `/s/${SHOP}`, "Choose a PDF"]] as const) {
  test(`first view of the ${name}`, async ({ browser }) => {
    const fast = await open(browser, false);
    await fast.page.goto(path);
    await fast.page.getByText(ready).waitFor();
    await fast.page.waitForTimeout(2500);
    console.log(`\n== ${name} (${path})`);
    console.log("downloaded on first view:", total(fast.sizes));
    for (const [url, n] of fast.sizes) console.log(`   ${kb(n).padStart(9)}  ${url}`);
    console.log("on a fast connection:", JSON.stringify(await read(fast.page)));
    await fast.ctx.close();

    const slow = await open(browser, true);
    const t0 = Date.now();
    await slow.page.goto(path, { waitUntil: "commit" });
    await slow.page.getByText(ready).waitFor({ timeout: 120_000 });
    const usable = Date.now() - t0;
    await slow.page.waitForTimeout(4000);
    const m = await read(slow.page);
    console.log(`on a slow phone: first paint ${m.firstPaint} ms, first content ${m.firstContentfulPaint} ms, usable ${usable} ms, layout shift ${m.layoutShift}, long tasks ${JSON.stringify(m.longTasks)}`);
    for (const s of m.shifts) console.log("   shift", s);
    await slow.ctx.close();
  });
}

test("the whole customer flow: layout shift, long tasks and what choosing a file downloads", async ({ browser }) => {
  for (const slow of [false, true]) {
    const { ctx, page, sizes } = await open(browser, slow);
    await page.goto(`/s/${SHOP}`);
    await page.getByText("Choose a PDF").waitFor({ timeout: 120_000 });
    const before = new Set(sizes.keys());
    let t0 = Date.now();
    await page.locator('input[type="file"]').setInputFiles(PDF);
    await page.locator(".preview canvas.ready").waitFor({ timeout: 180_000 });
    const preview = Date.now() - t0;
    t0 = Date.now();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("3 pages")).toBeVisible({ timeout: 120_000 });
    const uploaded = Date.now() - t0;
    await page.getByRole("button", { name: "More copies" }).click();
    await page.getByRole("radio", { name: "Some pages" }).check();
    await page.getByPlaceholder("1-3").fill("1-2");
    await page.getByRole("button", { name: "See exact price" }).click();
    await page.locator(".total").waitFor({ timeout: 60_000 });
    await page.waitForTimeout(600);
    const flow = await read(page);
    t0 = Date.now();
    await page.getByRole("button", { name: "Send to shop" }).click();
    await page.getByText("Waiting for the shop to approve your print.").waitFor({ timeout: 60_000 });
    const sent = Date.now() - t0;
    await page.waitForTimeout(1500);
    console.log(`\n== customer flow, ${slow ? "slow phone" : "fast connection"}`);
    console.log(`preview drawn ${preview} ms after choosing; upload and check ${uploaded} ms; status shown ${sent} ms after Send`);
    console.log(`layout shift ${flow.layoutShift}, long tasks ${JSON.stringify(flow.longTasks)}`);
    for (const s of flow.shifts) console.log("   shift", s);
    if (!slow) for (const [url, n] of sizes) if (!before.has(url) && !url.startsWith("/v1")) console.log(`   after choosing a file: ${kb(n).padStart(9)}  ${url}`);
    console.log("status page:", JSON.stringify(await read(page)));
    await ctx.close();
  }
});
