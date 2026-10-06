// A walk through every screen at phone widths, for looking at: one picture per screen with the widths side by side,
// and a list of anything that sticks out of the screen or is cut off. Not a test of behaviour (customer.spec.ts is).
//   E2E_TOOL=walk E2E_OUT=<folder> [E2E_SHOP_KEY=<dashboard key>]   through the same stack as the tests.
// Screens named "...-instant" are captured the moment their content exists, to show what a customer sees before any
// entrance motion has finished: everything must already be readable in them.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Browser, type Page } from "@playwright/test";
import { BROKEN, EMPTY, LOCKED, SHOP, TEXT_FILE, pdf, shop } from "./fixtures";

const OUT = process.env.E2E_OUT!;
const KEY = process.env.E2E_SHOP_KEY;
const LONG = pdf("blank(300)", "A very long file name for my final year project report submission draft version 7 final FINAL corrected.pdf");
const PHONES = [{ width: 320, height: 568 }, { width: 360, height: 740 }, { width: 412, height: 915 }];
const problems: string[] = [];
const taken = new Map<string, { width: number; file: string }[]>();

/** Anything wider than the screen, outside it, or cut off without an ellipsis. Runs in the page. */
function measure(): string[] {
  const W = document.documentElement.clientWidth;
  const found: string[] = [];
  const name = (el: Element) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().replace(/\s+/g, ".") : ""} "${(el.textContent ?? "").trim().slice(0, 40)}"`;
  if (document.documentElement.scrollWidth > W) found.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${W})`);
  for (const el of document.querySelectorAll("main *, .poster *")) {
    const r = el.getBoundingClientRect();
    // (marks that breathe carry a ring drawn larger than themselves; the price bar is meant to reach both edges)
    if (r.width === 0 || r.height === 0 || el.closest(".sr-only, svg, thead") || el.matches("i, .art") || el.querySelector(":scope > .bar")) continue;
    const cs = getComputedStyle(el);
    if (r.right > W + 0.5 || r.left < -0.5) found.push(`outside the screen (${Math.round(r.left)}..${Math.round(r.right)}): ${name(el)}`);
    if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== "ellipsis" && !(el instanceof HTMLInputElement)) found.push(`content wider than its box (${el.scrollWidth} > ${el.clientWidth}): ${name(el)}`);
  }
  return found;
}

async function shot(page: Page, name: string, opts: { full?: boolean } = {}) {
  const width = page.viewportSize()!.width;
  const file = join(OUT, `${name}@${width}.png`);
  await page.screenshot({ path: file, fullPage: opts.full ?? false, animations: "allow" });
  for (const p of await page.evaluate(measure)) problems.push(`${name}@${width}: ${p}`);
  if (!taken.has(name)) taken.set(name, []);
  taken.get(name)!.push({ width, file });
}
const settle = (page: Page) => page.waitForTimeout(700);          // longer than the slowest entrance motion

async function phone(browser: Browser, size: { width: number; height: number }) {
  const ctx = await browser.newContext({ viewport: size, isMobile: true, hasTouch: true, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const pick = (f: string) => page.locator('input[type="file"]').setInputFiles(f);

  await page.goto("/");
  await page.getByText("Print from your phone").waitFor();
  await shot(page, "01-home-instant");
  await page.getByRole("textbox").fill(SHOP);
  await page.locator(".found").waitFor(); await settle(page);
  await shot(page, "02-home-shop-found");
  await page.getByRole("textbox").fill("ZZZ999");
  await page.getByText("No shop has the code").waitFor();
  await shot(page, "03-home-no-such-shop");

  await page.goto(`/s/${SHOP}`);
  await page.locator(".drop").waitFor();
  await shot(page, "04-shop-instant");
  await settle(page);
  await shot(page, "05-shop");
  await pick(TEXT_FILE); await page.getByRole("alert").waitFor(); await shot(page, "06-not-a-pdf");
  await pick(EMPTY); await page.getByRole("alert").waitFor(); await shot(page, "07-empty-pdf");
  await pick(LOCKED); await page.getByRole("alert").waitFor(); await settle(page);
  await shot(page, "08-locked-pdf", { full: true });
  await pick(BROKEN); await page.getByRole("alert").waitFor(); await settle(page);
  await shot(page, "09-broken-pdf", { full: true });

  await pick(LONG);
  await page.locator(".preview canvas.ready").waitFor(); await settle(page);
  await shot(page, "10-file-chosen", { full: true });
  await shot(page, "11-file-chosen-screen");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator(".filecard").waitFor();
  await shot(page, "12-settings-instant");
  await settle(page);
  await shot(page, "13-settings", { full: true });
  await page.getByRole("spinbutton", { name: "Copies" }).fill("100");
  await page.getByRole("radio", { name: /^Colour/ }).check();
  await settle(page);
  await shot(page, "14-300-pages-100-copies", { full: true });
  await shot(page, "15-300-pages-100-copies-screen");
  await page.getByRole("radio", { name: "Some pages" }).check();
  await expect(page.getByPlaceholder("1-300")).toBeFocused();
  await settle(page);
  await shot(page, "16-some-pages-focused");
  await page.getByPlaceholder("1-300").fill("250-400");
  await settle(page);
  await shot(page, "17-bad-page-range");
  await page.getByPlaceholder("1-300").fill("1-300");
  await page.getByRole("button", { name: "See exact price" }).click();
  await page.locator(".total").waitFor(); await settle(page);
  await shot(page, "18-price-and-send-screen");
  await shot(page, "19-price-and-send", { full: true });
  await page.getByRole("button", { name: "Send to shop" }).click();
  await page.locator(".job").waitFor();
  await shot(page, "20-status-instant");
  await settle(page);
  await shot(page, "21-status-waiting", { full: true });

  // every other state, with the server's own wording for it (apps/api/app/wording.py)
  const orderId = page.url().split("/o/")[1];
  const real = await page.evaluate(async (id) => (await fetch(`/v1/orders/${id}`, { headers: { "X-Order-Secret": localStorage.getItem(`ap.order.${id}`)! } })).json(), orderId);
  const states: [string, string, string, string][] = [
    ["22-status-approved", "approved", "submitted", "Approved. Waiting for the printer."],
    ["23-status-printing", "printing", "submitted", "Sending to the printer."],
    ["24-status-completed", "completed", "closed", "Sent to printer. Collect it at the counter."],
    ["25-status-failed", "failed", "closed", "The shop could not print this. Please ask at the counter."],
    ["26-status-needs-attention", "needs_attention", "submitted", "The shop is checking this print. Please ask at the counter."],
    ["27-status-rejected", "rejected", "closed", "The shop declined this print."],
    ["28-status-cancelled", "cancelled", "cancelled", "Cancelled."],
    ["29-status-expired", "expired", "expired", "The shop did not approve this in time. Please start a new order."],
  ];
  for (const [name, job, order, words] of states) {
    await page.unroute("**/v1/orders/*");
    await page.route("**/v1/orders/*", (r) => r.fulfill({ json: { ...real, status: order, can_cancel: false, jobs: [{ ...real.jobs[0], status: job, customer_message: words }] } }));
    await page.reload();
    await page.getByText(words).waitFor(); await settle(page);
    await shot(page, name, { full: true });
  }
  await page.unroute("**/v1/orders/*");
  await page.reload();
  await page.locator(".job").waitFor();
  await page.route("**/v1/orders/*", (r) => r.abort());
  await page.getByText("Updates are delayed.").waitFor({ timeout: 30_000 });
  await shot(page, "30-status-delayed", { full: true });
  await page.unroute("**/v1/orders/*");

  await page.goto("/");
  await page.locator(".order-go").getByText("Waiting for the shop").waitFor(); await settle(page);
  await shot(page, "31-home-returning", { full: true });
  await page.goto(`/s/${SHOP}`);
  await page.locator(".order-go").getByText("Waiting for the shop").waitFor(); await settle(page);
  await shot(page, "32-shop-returning", { full: true });
  await page.goto("/s/ZZZ999");
  await page.getByRole("alert").waitFor(); await settle(page);
  await shot(page, "33-unknown-shop");
  await page.evaluate(() => localStorage.clear());
  await page.goto(`/o/${orderId}`);
  await page.getByText("Order not available").waitFor(); await settle(page);
  await shot(page, "34-order-other-phone");
  expect(shop("approve", real.short_code, SHOP).result).toBe("ok");      // leaves nothing waiting for the next width
  await ctx.close();
}

async function dashboard(browser: Browser, size: { width: number; height: number }) {
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1, isMobile: size.width < 600, hasTouch: size.width < 600 });
  const page = await ctx.newPage();
  await page.goto("/shop");
  await page.getByText("AutoPrint for shops").waitFor(); await settle(page);
  await shot(page, "40-dashboard-sign-in", { full: true });
  if (KEY) {
    await page.goto(`/shop#key=${KEY}`);
    await page.locator(".status-hero").waitFor();
    await shot(page, "41-dashboard-instant");
    await page.locator(".qr").waitFor(); await settle(page);
    await shot(page, "42-dashboard", { full: true });
    // the same page with the shop computer seen a moment ago
    await page.route("**/v1/shop/devices", async (r) => {
      const answer = await (await r.fetch()).json();
      await r.fulfill({ json: { ...answer, devices: answer.devices.map((d: object) => ({ ...d, last_seen_at: new Date().toISOString() })) } });
    });
    await page.reload();
    await page.getByText("Your shop is open for prints").waitFor(); await page.locator(".qr").waitFor(); await settle(page);
    await shot(page, "42b-dashboard-online", { full: true });
    await page.unroute("**/v1/shop/devices");
    await page.getByLabel("Code shown by the AutoPrint app").fill("ABCD2345");
    await page.getByRole("alert").waitFor(); await settle(page);
    await shot(page, "43-dashboard-wrong-code", { full: true });
    await page.route("**/v1/shop/**", (r) => r.fulfill({ status: 401, json: { error: { code: "unauthorized", message: "Sign in again." } } }));
    await page.reload();
    await page.getByText("Please sign in again").waitFor(); await settle(page);
    await shot(page, "44-dashboard-expired");
    await page.unroute("**/v1/shop/**");
  }
  await page.goto(`/poster/${SHOP}`);
  await page.locator(".poster img").waitFor(); await settle(page);
  await shot(page, "45-poster", { full: true });
  await ctx.close();
}

test("walk through every screen", async ({ browser }) => {
  for (const size of PHONES) await phone(browser, size);
  for (const size of [{ width: 360, height: 740 }, { width: 1280, height: 800 }]) await dashboard(browser, size);

  // one sheet per screen: the widths side by side at their real size
  const sheet = await (await browser.newContext({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 1 })).newPage();
  for (const [name, shots] of taken) {
    const wide = shots.some((s) => s.width > 600);
    const imgs = shots.map((s) => `<figure><figcaption>${s.width}</figcaption><img ${wide && s.width > 600 ? 'style="width:1000px"' : ""} src="data:image/png;base64,${readFileSync(s.file).toString("base64")}"></figure>`).join("");
    await sheet.setContent(`<body style="margin:0;padding:12px;background:#888;display:flex;gap:14px;align-items:flex-start;font:12px sans-serif;width:max-content">
      <style>figure{margin:0}figcaption{color:#fff;margin-bottom:4px}img{display:block}</style>${imgs}</body>`);
    await sheet.setViewportSize({ width: 200, height: 100 });
    await sheet.setViewportSize(await sheet.evaluate(() => ({ width: document.body.scrollWidth, height: document.body.scrollHeight })));
    await sheet.screenshot({ path: join(OUT, `sheet-${name}.png`), fullPage: true });
  }
  writeFileSync(join(OUT, "problems.txt"), problems.join("\n") + "\n");
  console.log(problems.length ? `\n${problems.length} layout findings:\n${problems.join("\n")}` : "\nno layout findings");
});
