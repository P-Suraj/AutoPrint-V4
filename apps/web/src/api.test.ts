import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, REQUEST_TIMEOUT_MS, UPLOAD_STALL_MS, api, uploadPdf } from "./api";

// A stand-in for the browser's upload object: the test decides what the network does.
class FakeXhr {
  static last: FakeXhr;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  status = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  headers: Record<string, string> = {};
  sent: unknown = null;
  aborted = false;
  constructor() { FakeXhr.last = this; }
  open() { /* nothing to do */ }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  send(body: unknown) { this.sent = body; }
  abort() { this.aborted = true; this.onabort?.(); }
}

const file = new File(["%PDF-1.4 test"], "a.pdf", { type: "application/pdf" });

describe("uploading the PDF", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("XMLHttpRequest", FakeXhr); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("sends the raw file with the given headers and reports progress", async () => {
    const seen: number[] = [];
    const done = uploadPdf("https://storage.example/put", { "Content-Type": "application/pdf" }, file, (f) => seen.push(f));
    const x = FakeXhr.last;
    expect(x.sent).toBe(file);                                         // never multipart
    expect(x.headers["Content-Type"]).toBe("application/pdf");
    x.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    x.status = 200; x.onload?.();
    await expect(done).resolves.toBeUndefined();
    expect(seen).toEqual([0.5]);
  });

  it("a refusal from storage is an error, not a success", async () => {
    const done = uploadPdf("u", {}, file);
    FakeXhr.last.status = 403; FakeXhr.last.onload?.();
    await expect(done).rejects.toMatchObject({ code: "upload_failed", status: 403 });
  });

  it("a dropped connection says the upload was interrupted", async () => {
    const done = uploadPdf("u", {}, file);
    FakeXhr.last.onerror?.();
    await expect(done).rejects.toMatchObject({ code: "network", message: expect.stringContaining("interrupted") });
  });

  it("an upload that stops moving is ended instead of spinning for ever", async () => {
    const done = uploadPdf("u", {}, file);
    const caught = done.catch((e: ApiError) => e);
    const x = FakeXhr.last;
    vi.advanceTimersByTime(UPLOAD_STALL_MS - 1000);
    x.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 10 });      // still moving: the clock starts again
    vi.advanceTimersByTime(UPLOAD_STALL_MS - 1000);
    expect(x.aborted).toBe(false);
    vi.advanceTimersByTime(2000);
    expect(x.aborted).toBe(true);
    expect(await caught).toMatchObject({ code: "network" });
  });
});

describe("talking to the API", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("gives the server's own message for a known error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "rate_limited", message: "Too many requests. Please wait a moment." } }),
      { status: 429, headers: { "Content-Type": "application/json" } })));
    await expect(api.createOrder("TST001")).rejects.toMatchObject({ code: "rate_limited", status: 429, message: "Too many requests. Please wait a moment." });
  });

  it("never shows a raw page from the host as the message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>502 Bad Gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } })));
    await expect(api.getShop("TST001")).rejects.toMatchObject({ code: "unknown", status: 502, message: "Something went wrong. Please try again." });
  });

  it("says the connection failed when the network is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api.getShop("TST001")).rejects.toMatchObject({ code: "network", message: expect.stringContaining("Could not reach AutoPrint") });
  });

  it("a request with no answer ends by itself as a connection failure", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_req: Request, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const caught = api.getShop("TST001").catch((e: ApiError) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 10);
    expect(await caught).toMatchObject({ code: "network" });
  });
});
