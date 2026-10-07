import { defineConfig, devices } from "@playwright/test";

// Run through e2e/run_web_e2e.py, which starts the API, the database and the dev server first.
//   E2E_CHANNEL=msedge  uses the Edge that ships with Windows (Chromium engine) when Playwright's own download is not installed.
//   E2E_ENGINE=webkit   runs the same tests in Playwright's WebKit with an iPhone profile (the nearest thing to Safari on Windows).
//   E2E_TOOL=walk|perf  runs one of the tools in e2e/*.tool.ts instead of the tests (screenshots of every screen; load measurements).
const webkit = process.env.E2E_ENGINE === "webkit";
const tool = process.env.E2E_TOOL;

export default defineConfig({
  testDir: "./e2e",
  testMatch: tool ? `${tool}.tool.ts` : "*.spec.ts",
  timeout: tool ? 300_000 : 90_000,
  workers: 1,
  reporter: "list",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173", trace: "off" },
  projects: [webkit
    ? { name: "iphone-webkit", use: { ...devices["iPhone 13"], browserName: "webkit" } }
    : { name: "android-chrome", use: { ...devices["Pixel 7"], browserName: "chromium", channel: process.env.E2E_CHANNEL || undefined } }],
});
