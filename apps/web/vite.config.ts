import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs on :8000. In production the same paths are rewritten by the host
// (vercel.json), so the browser always calls same-origin /v1/... and never needs CORS or cookies.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
