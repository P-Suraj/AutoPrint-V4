import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";

const SHOP = process.env.E2E_SHOP_CODE!;
const PDF = process.env.E2E_PDF!;
const TEXT_FILE = process.env.E2E_TEXT_FILE!;
const PY = process.env.E2E_PYTHON!;
const SIM = process.env.E2E_SHOP_SIM!;

const shop = (...args: string[]) => JSON.parse(execFileSync(PY, [SIM, ...args], { encoding: "utf8" }));

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
