// In-browser preview of the customer's own file (decision D-9). Nothing is uploaded to render this.
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";

// pdf.js is large. It is loaded only when a file is chosen, so the first screen stays small on mobile data.
async function loadPdfjs() {
  const [pdfjs, worker] = await Promise.all([import("pdfjs-dist"), import("pdfjs-dist/build/pdf.worker.min.mjs?url")]);
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  return pdfjs;
}

export async function readPageCount(file: File): Promise<number> {
  const pdfjs = await loadPdfjs();
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
  const n = doc.numPages;
  await doc.destroy();
  return n;
}

export function PdfPreview({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    let loaded: PDFDocumentProxy | null = null;
    Promise.all([loadPdfjs(), file.arrayBuffer()]).then(([pdfjs, buf]) => pdfjs.getDocument({ data: new Uint8Array(buf) }).promise).then((d) => {
      loaded = d;
      if (alive) { setDoc(d); setPage(1); } else d.destroy();
    }).catch(() => alive && setFailed(true));
    return () => { alive = false; loaded?.destroy(); };
  }, [file]);

  useEffect(() => {
    if (!doc || !canvas.current) return;
    let cancelled = false;
    doc.getPage(page).then((p) => {
      const el = canvas.current;
      if (!el || cancelled) return;
      const base = p.getViewport({ scale: 1 });
      const width = Math.min(el.parentElement?.clientWidth ?? 320, 480);
      const viewport = p.getViewport({ scale: (width / base.width) * (window.devicePixelRatio || 1) });
      el.width = viewport.width; el.height = viewport.height;
      el.style.width = `${viewport.width / (window.devicePixelRatio || 1)}px`;
      const task = p.render({ canvasContext: el.getContext("2d")!, viewport });
      task.promise.catch(() => undefined);
    });
    return () => { cancelled = true; };
  }, [doc, page]);

  if (failed) return <p className="note">This file could not be previewed here. You can still send it; the shop will check it.</p>;
  return (
    <div className="preview">
      <canvas ref={canvas} aria-label={`Preview of page ${page}`} />
      {doc && (
        <div className="pager">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>Previous</button>
          <span>Page {page} of {doc.numPages}</span>
          <button type="button" onClick={() => setPage((p) => Math.min(doc.numPages, p + 1))} disabled={page >= doc.numPages}>Next</button>
        </div>
      )}
    </div>
  );
}
