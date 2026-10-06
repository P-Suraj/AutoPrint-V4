import { readFileSync } from "node:fs";
import { createGzip } from "node:zlib";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// `vite preview` serves the production build the way the host does, so the build can be tried and measured locally:
// the same response headers (vercel.json, so the Content-Security-Policy is in force) and compressed text files.
function hostHeaders(): Record<string, string> {
  try {
    const host = JSON.parse(readFileSync(new URL("../../vercel.json", import.meta.url), "utf8")) as { headers?: { headers: { key: string; value: string }[] }[] };
    return Object.fromEntries((host.headers ?? []).flatMap((h) => h.headers.map((x) => [x.key, x.value])));
  } catch { return {}; }
}
function compressedPreview(): Plugin {
  return {
    name: "autoprint-compressed-preview",
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? "").split("?")[0];
        const text = /\.(js|mjs|css|html|json|webmanifest|svg)$/.test(path) || (!path.includes(".") && !path.startsWith("/v1"));
        if (req.method !== "GET" || !text || !/\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""))) return next();
        const head = res.writeHead.bind(res), write = res.write.bind(res), end = res.end.bind(res);
        let gzip: ReturnType<typeof createGzip> | null = null;
        res.writeHead = ((code: number, ...rest: unknown[]) => {
          if (code === 200) {
            for (const h of rest) if (h && typeof h === "object") for (const k of Object.keys(h)) if (k.toLowerCase() === "content-length") delete (h as Record<string, unknown>)[k];
            res.removeHeader("Content-Length"); res.setHeader("Content-Encoding", "gzip"); res.setHeader("Vary", "Accept-Encoding");
            gzip = createGzip();
            gzip.on("data", (chunk) => write(chunk)); gzip.on("end", () => end());
          }
          return (head as (...a: unknown[]) => typeof res)(code, ...rest);
        }) as typeof res.writeHead;
        res.write = ((chunk: never, ...rest: never[]) => (gzip ? (gzip.write(chunk), true) : write(chunk, ...rest))) as typeof res.write;
        res.end = ((chunk?: never, ...rest: never[]) => {
          if (!gzip) return end(chunk, ...rest);
          if (chunk && typeof chunk !== "function") gzip.write(chunk);
          gzip.end();
          return res;
        }) as typeof res.end;
        next();
      });
    },
  };
}

// In development the API runs on :8000. In production the same paths are rewritten by the host
// (vercel.json), so the browser always calls same-origin /v1/... and never needs CORS or cookies.
export default defineConfig({
  plugins: [react(), compressedPreview()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
  preview: { headers: hostHeaders() },
  // Every package the pages use is named, so the dev server prepares all of them before the first page is served.
  // Left to find them itself, it can meet pdf.js (loaded only when a file is chosen) or the QR code library late and
  // reload the page under a browser test that is half way through an upload.
  optimizeDeps: { include: ["react", "react-dom/client", "react/jsx-runtime", "react/jsx-dev-runtime", "react-router-dom", "openapi-fetch", "qrcode", "pdfjs-dist/legacy/build/pdf.mjs"] },
  // unit tests have no page address, so the API client is given an absolute one (requests are faked, nothing is called)
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.ts", "src/**/*.test.tsx"], env: { VITE_API_BASE_URL: "http://api.test" } },
});
