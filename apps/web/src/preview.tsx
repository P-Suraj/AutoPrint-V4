// In-browser preview of the customer's own file (decision D-9). Nothing is uploaded to render this.
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";

// pdf.js is large. It is loaded only when a file is chosen, so the first screen stays small on mobile data.
// The "legacy" build is the one that runs on phones a few years old (the default build needs a 2024 browser);
// parsing happens in its worker, off the main thread.
async function loadPdfjs() {
  const [pdfjs, worker] = await Promise.all([import("pdfjs-dist/legacy/build/pdf.mjs"), import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url")]);
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  return pdfjs;
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

export async function inspectPdf(file: File): Promise<PdfCheck> {
  try {
    const pdfjs = await loadPdfjs();
    const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    const pages = doc.numPages;
    await doc.destroy();
    return pages >= 1 ? { kind: "ok", pages } : { kind: "invalid" };
  } catch (e) { return classifyPdfError(e); }
}

export function PdfPreview({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [failed, setFailed] = useState<PdfCheck["kind"] | null>(null);

  useEffect(() => {
    let alive = true;
    let loaded: PDFDocumentProxy | null = null;
    setFailed(null); setDoc(null);            // a new file starts clean: the last file's failure says nothing about this one
    Promise.all([loadPdfjs(), file.arrayBuffer()]).then(([pdfjs, buf]) => pdfjs.getDocument({ data: new Uint8Array(buf) }).promise).then((d) => {
      loaded = d;
      if (alive) { setDoc(d); setPage(1); } else d.destroy();
    }).catch((e) => alive && setFailed(classifyPdfError(e).kind));
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

  if (failed === "encrypted") return <p className="note">This PDF is password-protected, so the shop could not print it. Remove the password and choose it again.</p>;
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
