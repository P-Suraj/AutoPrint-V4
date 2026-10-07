// In-browser preview of the customer's own file (decision D-9). Nothing is uploaded to render this.
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";
// only the address of the worker script (a short string); the script itself is fetched when pdf.js starts
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

// pdf.js is large. It is loaded only when a file is chosen, so the first screen stays small on mobile data.
// The "legacy" build is the one that runs on phones a few years old (the default build needs a 2024 browser);
// parsing happens in its worker, off the main thread.
async function loadPdfjs() {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs;
}

// On a slow connection the reader (about 120 KB) and its worker (about 410 KB) take longer to arrive than the customer
// takes to pick a file. So the shop page asks for both once it has nothing else to do: the first screen is already
// shown and usable by then, and the preview no longer starts its download from nothing.
let warmed = false;
export function warmPdfReader(): void {
  if (warmed) return;
  warmed = true;
  // the worker is only put in the browser's cache here (it starts when a file is opened); the reader itself is loaded
  fetch(workerUrl).then((r) => r.blob()).catch(() => undefined);
  loadPdfjs().catch(() => { warmed = false; });
}
/** Warms the reader when the page is idle. Someone who asked their browser to save data pays for it only on touching the file button. */
export function warmPdfReaderWhenIdle(): () => void {
  if ((navigator as { connection?: { saveData?: boolean } }).connection?.saveData) return () => undefined;
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(warmPdfReader, { timeout: 3000 });
    return () => window.cancelIdleCallback(id);
  }
  const id = window.setTimeout(warmPdfReader, 1200);
  return () => window.clearTimeout(id);
}

/**
 * What this browser can tell about the file before it is uploaded.
 * "unknown" means the reader itself could not run here (old browser, script not loaded): that says nothing about
 * the file, so the upload goes ahead and the server, which checks every file anyway, gives the answer.
 */
export type PdfCheck = { kind: "ok"; pages: number } | { kind: "encrypted" } | { kind: "invalid" } | { kind: "unknown" };

/** pdf.js names its errors; only these two are statements about the file itself. */
export function classifyPdfError(e: unknown): Exclude<PdfCheck, { kind: "ok" }> {
  const name = (e as { name?: string } | null)?.name;
  if (name === "PasswordException") return { kind: "encrypted" };
  if (name === "InvalidPDFException") return { kind: "invalid" };
  return { kind: "unknown" };
}

// What the preview already found out about a file, so Continue does not open the same file a second time.
const seen = new WeakMap<File, PdfCheck>();
/** How long Continue waits for this check. The preview is a courtesy: on a slow connection it must not hold the order up. */
export const INSPECT_WAIT_MS = 3000;

async function readPdf(file: File): Promise<PdfCheck> {
  try {
    const pdfjs = await loadPdfjs();
    const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    const pages = doc.numPages;
    await doc.destroy();
    return pages >= 1 ? { kind: "ok", pages } : { kind: "invalid" };
  } catch (e) { return classifyPdfError(e); }
}

/** Answers "unknown" when the reader has not arrived in time: the upload then goes ahead and the server gives the answer. */
export async function inspectPdf(file: File, waitMs = INSPECT_WAIT_MS): Promise<PdfCheck> {
  const known = seen.get(file);
  if (known) return known;
  let timer: number | undefined;
  const late = new Promise<PdfCheck>((resolve) => { timer = window.setTimeout(() => resolve({ kind: "unknown" }), waitMs); });
  try { return await Promise.race([readPdf(file), late]); } finally { window.clearTimeout(timer); }
}

/** What the customer is told about a file that cannot be printed. One wording, wherever it is found out. */
export const PDF_PROBLEM = {
  encrypted: "This PDF is password-protected. Remove the password and try again.",
  invalid: "This PDF could not be read. Try saving or exporting it again.",
} as const;
export type PdfProblem = keyof typeof PDF_PROBLEM;

/** `onProblem` is told when the file itself cannot be printed; the page that asked then says so in its own place. */
export function PdfPreview({ file, onProblem }: { file: File; onProblem?: (kind: PdfProblem) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [failed, setFailed] = useState<PdfCheck["kind"] | null>(null);
  const told = useRef(onProblem);
  told.current = onProblem;

  useEffect(() => {
    let alive = true;
    let loaded: PDFDocumentProxy | null = null;
    setFailed(null); setDoc(null);            // a new file starts clean: the last file's failure says nothing about this one
    Promise.all([loadPdfjs(), file.arrayBuffer()]).then(([pdfjs, buf]) => pdfjs.getDocument({ data: new Uint8Array(buf) }).promise).then((d) => {
      loaded = d;
      seen.set(file, d.numPages >= 1 ? { kind: "ok", pages: d.numPages } : { kind: "invalid" });
      if (alive) { setDoc(d); setPage(1); } else d.destroy();
    }).catch((e) => {
      if (!alive) return;
      const found = classifyPdfError(e);
      const kind = found.kind;
      if (kind !== "unknown") seen.set(file, found);
      setFailed(kind);
      if (kind === "encrypted" || kind === "invalid") told.current?.(kind);
    });
    return () => { alive = false; loaded?.destroy(); };
  }, [file]);

  useEffect(() => {
    if (!doc || !canvas.current) return;
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null;
    doc.getPage(page).then((p) => {
      const el = canvas.current;
      if (!el || cancelled) return;
      const base = p.getViewport({ scale: 1 });
      const stage = el.parentElement;
      // fit the page inside the space kept for it, and never draw more pixels than a phone needs
      const fit = Math.min((stage?.clientWidth ?? 320) / base.width, (stage?.clientHeight ?? 320) / base.height);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = p.getViewport({ scale: fit * ratio });
      el.width = Math.floor(viewport.width); el.height = Math.floor(viewport.height);
      el.style.width = `${Math.floor(viewport.width / ratio)}px`;
      el.style.height = `${Math.floor(viewport.height / ratio)}px`;
      task = p.render({ canvasContext: el.getContext("2d")!, viewport });
      task.promise.then(() => { if (!cancelled) el.classList.add("ready"); }).catch(() => undefined);
    }).catch(() => undefined);
    return () => { cancelled = true; task?.cancel(); };
  }, [doc, page]);

  if (failed === "encrypted" || failed === "invalid") return onProblem ? null : <p className="note">{PDF_PROBLEM[failed]}</p>;
  if (failed) return <p className="note">No preview for this file here. You can still continue; the file is checked when it is uploaded.</p>;
  return (
    <div className="preview">
      {/* the space is kept from the start, so nothing below jumps when the page appears */}
      <div className="preview-stage"><canvas ref={canvas} aria-label={`Preview of page ${page}`} /></div>
      <div className="pager">
        <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={!doc || page <= 1}>Previous</button>
        <span>{doc ? `Page ${page} of ${doc.numPages}` : "Opening…"}</span>
        <button type="button" onClick={() => setPage((p) => Math.min(doc?.numPages ?? 1, p + 1))} disabled={!doc || page >= doc.numPages}>Next</button>
      </div>
    </div>
  );
}
