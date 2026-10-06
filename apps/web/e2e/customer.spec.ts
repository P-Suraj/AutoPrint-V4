import { expect, test, type Page } from "@playwright/test";
import { BROKEN, EMPTY, LOCKED, PDF, SHOP, TEXT_FILE, shop } from "./fixtures";

/** Counts requests of one kind, so a test can say how many times the server was really asked. */
function count(page: Page, method: string, path: RegExp): () => number {
  let n = 0;
  page.on("request", (r) => { if (r.method() === method && path.test(new URL(r.url()).pathname)) n += 1; });
  return () => n;
}
const NEW_ORDER = /^\/v1\/shops\/[^/]+\/orders$/;
const gone = { status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "order_not_found", message: "This order link is not valid any more." } }) };
const yourOrders = (page: Page) => page.getByRole("region", { name: "Your orders" });

async function uploadThreePagePdf(page: Page) {
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("3 pages")).toBeVisible();
}

async function sendThreePagePdf(page: Page) {
  await page.goto(`/s/${SHOP}`);
  await expect(page.getByRole("heading", { name: "E2E Copy Centre" })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("3 pages")).toBeVisible();
  await expect(page.getByText("About")).toContainText("₹6");                      // estimate from the browser
  await page.getByRole("button", { name: "See exact price" }).click();
  await expect(page.locator(".total")).toHaveText("₹6");                           // authoritative price from the server
  await page.getByRole("button", { name: "Send to shop" }).click();
  await expect(page).toHaveURL(/\/o\/[0-9a-f-]{36}$/);
}

test("a student sends a PDF, the shop approves it, and it is sent to the printer", async ({ page }) => {
  await sendThreePagePdf(page);
  const orderId = page.url().split("/o/")[1];
  const short = (await page.locator(".code").innerText()).trim();
  expect(short).toMatch(/^[A-Z0-9]{4}$/);

  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel this print" })).toBeVisible();

  // the secret is the only credential: it must not be in the URL or visible on the page
  const secret = await page.evaluate((id) => localStorage.getItem(`ap.order.${id}`), orderId);
  expect(secret).toMatch(/^[0-9a-f]{64}$/);
  expect(page.url()).not.toContain(secret!);
  expect(await page.content()).not.toContain(secret!);

  expect(shop("approve", short, SHOP).result).toBe("ok");
  await expect(page.getByText("Approved. Waiting for the printer.")).toBeVisible({ timeout: 20_000 });

  expect(shop("print", short, SHOP).result).toBe("ok");
  await expect(page.getByText("Sent to printer.")).toBeVisible({ timeout: 20_000 });
  expect((await page.locator("main").innerText()).toLowerCase()).not.toMatch(/\bprinted\b/);   // decision O-8
  await expect(page.getByRole("button", { name: "Cancel this print" })).toHaveCount(0);
});

test("the customer can cancel before the shop approves", async ({ page }) => {
  await sendThreePagePdf(page);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Cancel this print" }).click();
  await expect(page.getByText("Cancelled.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel this print" })).toHaveCount(0);
});

test("a file that is not a PDF is refused before anything is uploaded", async ({ page }) => {
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(TEXT_FILE);
  await expect(page.getByRole("alert")).toContainText("Only PDF files can be printed.");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
});

test("an unknown shop code shows an error, not an empty or fake page", async ({ page }) => {
  await page.goto("/s/ZZZ999");
  await expect(page.getByRole("alert")).toContainText("not recognised");
});

test("an order link opened in another browser does not reveal the order", async ({ browser, page }) => {
  await sendThreePagePdf(page);
  const url = page.url();
  const other = await browser.newContext();
  const p2 = await other.newPage();
  await p2.goto(url);
  await expect(p2.getByText("can only be opened in the browser where it was started")).toBeVisible();
  await other.close();
});

test("when the API is unreachable the customer sees an error and nothing pretends to work", async ({ page }) => {
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await page.route("**/v1/shops/*/orders", (r) => r.abort());
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toContainText("Could not reach AutoPrint");
  await expect(page.getByText("About")).toHaveCount(0);
});

// ---- coming back to an order

test("after the tab is closed, the home page and the shop page lead back to the order", async ({ page, context }) => {
  await sendThreePagePdf(page);
  const orderId = page.url().split("/o/")[1];
  const short = (await page.locator(".code").innerText()).trim();
  await page.close();

  const again = await context.newPage();
  await again.goto("/");
  await expect(yourOrders(again).getByText("Your order", { exact: true })).toBeVisible();
  const onHome = yourOrders(again).getByRole("link");
  await expect(onHome).toContainText(short);
  await expect(onHome).toContainText("Waiting for the shop to approve your print.");   // the server's words, not a guess
  await expect(onHome).toContainText("E2E Copy Centre");

  await again.goto(`/s/${SHOP}`);
  const onShop = yourOrders(again).getByRole("link");
  await expect(onShop).toContainText(short);
  await expect(onShop).toContainText("Waiting for the shop to approve your print.");
  await onShop.click();
  await expect(again).toHaveURL(new RegExp(`/o/${orderId}$`));
  await expect(again.locator(".ticket .code")).toHaveText(short);
  await expect(again.getByRole("button", { name: "Cancel this print" })).toBeVisible();
});

for (const where of ["home", "shop"] as const) {
  test(`the order card on the ${where} page disappears when the server says the order is gone`, async ({ page, context }) => {
    await sendThreePagePdf(page);
    const orderId = page.url().split("/o/")[1];
    await page.close();

    const again = await context.newPage();
    await again.route(`**/v1/orders/${orderId}`, (r) => r.fulfill(gone));
    await again.goto(where === "home" ? "/" : `/s/${SHOP}`);
    await expect(again.getByText(where === "home" ? "Print from your phone" : "Choose a PDF")).toBeVisible();
    await expect(yourOrders(again)).toHaveCount(0);
    // and it is forgotten on the phone, secret included: nothing is left to show next time
    await expect.poll(() => again.evaluate((id) => [localStorage.getItem("ap.orders"), localStorage.getItem(`ap.order.${id}`)], orderId)).toEqual(["[]", null]);
    await again.unroute(`**/v1/orders/${orderId}`);
    await again.reload();
    await expect(again.getByText(where === "home" ? "Print from your phone" : "Choose a PDF")).toBeVisible();
    await expect(yourOrders(again)).toHaveCount(0);
  });
}

test("an order that is gone says so on its own page", async ({ page }) => {
  await sendThreePagePdf(page);
  await page.route("**/v1/orders/*", (r) => r.fulfill(gone));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Order not available" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("not valid any more");
});

// ---- the file survives a refresh

test("a refresh at the Settings step keeps the uploaded file and the chosen settings", async ({ page }) => {
  const orders = count(page, "POST", NEW_ORDER);
  await uploadThreePagePdf(page);
  await page.getByRole("button", { name: "More copies" }).click();
  await page.getByRole("radio", { name: /^Colour/ }).check();
  await expect(page.locator(".estimate strong")).toHaveText("₹60");                // 3 pages x 2 copies x ₹10

  await page.reload();
  await expect(page.getByText("three.pdf")).toBeVisible();
  await expect(page.getByText("3 pages")).toBeVisible();
  await expect(page.getByRole("spinbutton", { name: "Copies" })).toHaveValue("2");
  await expect(page.getByRole("radio", { name: /^Colour/ })).toBeChecked();
  await expect(page.locator(".estimate strong")).toHaveText("₹60");
  await expect(page.locator('input[type="file"]')).toHaveCount(0);                  // not asked for the file again

  await page.getByRole("button", { name: "See exact price" }).click();
  await expect(page.locator(".total")).toHaveText("₹60");
  await page.getByRole("button", { name: "Send to shop" }).click();
  await expect(page).toHaveURL(/\/o\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();
  expect(orders()).toBe(1);                                                         // the same order all the way through
});

// ---- impatient fingers

test("a double tap on Continue and on Send makes one order and sends it once", async ({ page }) => {
  const orders = count(page, "POST", NEW_ORDER);
  const submits = count(page, "POST", /^\/v1\/orders\/[^/]+\/submit$/);
  const twice = (name: string) => page.getByRole("button", { name }).evaluate((b: HTMLButtonElement) => { b.click(); b.click(); });

  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await twice("Continue");
  await expect(page.getByText("3 pages")).toBeVisible();
  await twice("See exact price");
  await expect(page.locator(".total")).toHaveText("₹6");
  await twice("Send to shop");
  await expect(page).toHaveURL(/\/o\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();
  expect(orders()).toBe(1);
  expect(submits()).toBe(1);

  await page.goto("/");
  await expect(yourOrders(page).getByRole("link")).toHaveCount(1);
});

// ---- files that cannot be printed

test("a password-protected PDF is refused with its own message and nothing is uploaded", async ({ page }) => {
  const orders = count(page, "POST", NEW_ORDER);
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(LOCKED);
  await expect(page.getByRole("alert")).toHaveText("This PDF is password-protected. Remove the password and try again.");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);      // nothing to continue with
  await expect(page.getByText("locked.pdf")).toBeVisible();
  expect(orders()).toBe(0);
});

test("an empty PDF is refused with its own message", async ({ page }) => {
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(EMPTY);
  await expect(page.getByRole("alert")).toHaveText("This file is empty. Choose another PDF.");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
});

test("a broken PDF is refused with its own message, and a good file chosen next goes through", async ({ page }) => {
  const orders = count(page, "POST", NEW_ORDER);
  await page.goto(`/s/${SHOP}`);
  await page.locator('input[type="file"]').setInputFiles(BROKEN);
  await expect(page.getByRole("alert")).toHaveText("This PDF could not be read. Try saving or exporting it again.");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
  expect(orders()).toBe(0);
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await expect(page.getByRole("alert")).toHaveCount(0);                             // the message was about that file only
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("3 pages")).toBeVisible();
});

// ---- a phone that loses its connection

test("the status page says updates are delayed when the network drops, and catches up when it returns", async ({ page, context }) => {
  await sendThreePagePdf(page);
  const short = (await page.locator(".code").innerText()).trim();
  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();

  await context.setOffline(true);
  await expect(page.getByText("Updates are delayed.")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();   // the last true answer stays
  await expect(page.locator(".ticket .code")).toHaveText(short);

  expect(shop("approve", short, SHOP).result).toBe("ok");                           // the shop acts while the phone is offline
  await context.setOffline(false);
  await expect(page.getByText("Approved. Waiting for the printer.")).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("Updates are delayed.")).toHaveCount(0);
});

// ---- cancelling

test("saying no to the cancel question keeps the order; a cancelled order can be removed from the phone", async ({ page }) => {
  const cancels = count(page, "POST", /\/cancel$/);
  await sendThreePagePdf(page);
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "Cancel this print" }).click();
  await expect(page.getByText("Waiting for the shop to approve your print.")).toBeVisible();
  expect(cancels()).toBe(0);

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Cancel this print" }).click();
  await expect(page.getByText("Cancelled.")).toBeVisible();
  expect(cancels()).toBe(1);
  await expect(page.getByText("This page updates by itself")).toHaveCount(0);

  await page.getByRole("link", { name: "Print another file" }).click();
  await expect(yourOrders(page).getByRole("link")).toContainText("Cancelled.");
  await yourOrders(page).getByRole("button", { name: /^Remove order/ }).click();
  await expect(yourOrders(page)).toHaveCount(0);
});
