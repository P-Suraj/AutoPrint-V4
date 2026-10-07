import { readFileSync } from "node:fs";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `vite preview` serves the production build the way the host does, so the build can be tried and measured locally:
// the same response headers (vercel.json, so the Content-Security-Policy is in force). It compresses text files by
// itself; a second compression step here would send the scripts compressed twice and the page would stay blank.
function hostHeaders(): Record<string, string> {
  try {
    const host = JSON.parse(readFileSync(new URL("../../vercel.json", import.meta.url), "utf8")) as { headers?: { headers: { key: string; value: string }[] }[] };
    return Object.fromEntries((host.headers ?? []).flatMap((h) => h.headers.map((x) => [x.key, x.value])));
  } catch { return {}; }
}

// In development the API runs on :8000. In production the same paths are rewritten by the host
// (vercel.json), so the browser always calls same-origin /v1/... and never needs CORS or cookies.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
  preview: { headers: hostHeaders() },
  // Every package the pages use is named, so the dev server prepares all of them before the first page is served.
  // Left to find them itself, it can meet pdf.js (loaded only when a file is chosen) or the QR code library late and
  // reload the page under a browser test that is half way through an upload.
  optimizeDeps: { include: ["react", "react-dom/client", "react/jsx-runtime", "react/jsx-dev-runtime", "react-router-dom", "openapi-fetch", "qrcode", "pdfjs-dist/legacy/build/pdf.mjs"] },
  // unit tests have no page address, so the API client is given an absolute one (requests are faked, nothing is called)
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.ts", "src/**/*.test.tsx"], env: { VITE_API_BASE_URL: "http://api.test" } },
});
