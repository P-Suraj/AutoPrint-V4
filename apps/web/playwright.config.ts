import { defineConfig, devices } from "@playwright/test";

// Run through e2e/run_web_e2e.py, which starts the API, the database and the dev server first.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  reporter: "list",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173", trace: "off", ...devices["Pixel 7"] },
  // E2E_CHANNEL=msedge uses the Edge that ships with Windows (Chromium engine) when Playwright's own download is not installed.
  projects: [{ name: "android-chrome", use: { browserName: "chromium", channel: process.env.E2E_CHANNEL || undefined } }],
});
