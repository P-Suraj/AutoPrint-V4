// The counter QR opens /s/<SHOP CODE>. One screen walks the customer from file to submitted order.
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api, uploadPdf, type Schemas } from "../api";
import { estimate, rupees, type Options, type Rates } from "../estimate";
import { YourOrders } from "../orders";
import { PDF_PROBLEM, PdfPreview, inspectPdf, warmPdfReader, warmPdfReaderWhenIdle, type PdfProblem } from "../preview";
import { clearDraft, loadDraft, loadSecret, rememberOrder, saveDraft, saveSecret } from "../store";
import { rememberShop } from "../shopCode";
import { Icon, Segmented, Stepper, Steps, TopBar, fileSize } from "../ui";

const MAX_BYTES = 26_214_400;
// answers that mean a kept draft order cannot take another file
const ORDER_UNUSABLE = new Set(["order_not_found", "order_expired", "order_not_draft", "too_many_documents"]);
// answers that mean the uploaded file is no longer there to be priced or sent (an unsent file is kept for an hour)
const FILE_GONE = new Set(["order_not_found", "order_expired", "document_not_ready", "document_not_found"]);
// with no price list from the server the settings can still be checked; the price then comes from the exact quote
const NO_RATES: Rates = { bw: { simplex: [], duplex: [] }, color: { simplex: [], duplex: [] } };

type Kept = { orderId: string; secret: string; shortCode: string };
type Uploaded = Kept & { documentId: string; pageCount: number; fileName: string };
type LoadError = { message: string; retry: boolean };

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}
const code = (e: unknown) => (e instanceof ApiError ? e.code : "");

// A different shop code is a different visit: nothing chosen for one shop may leak into another.
export default function ShopPage() {
  const { shopCode = "" } = useParams();
  return <ShopFlow key={shopCode} shopCode={shopCode} />;
}

function ShopFlow({ shopCode }: { shopCode: string }) {
  const navigate = useNavigate();
  // What this tab was doing before a refresh or the back button (see store.ts): the uploaded file is not asked for again.
  const restored = useMemo(() => {
    const d = loadDraft(shopCode);
    const secret = d ? loadSecret(d.orderId) : null;
    return d && secret ? { d, kept: { orderId: d.orderId, secret, shortCode: d.shortCode } } : null;
  }, [shopCode]);
  const [shop, setShop] = useState<Schemas["ShopPublic"] | null>(null);
  const [rates, setRates] = useState<Schemas["RateCardPublic"] | null>(null);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [unprintable, setUnprintable] = useState<PdfProblem | null>(null);   // the chosen file cannot be printed: say why, offer nothing else
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [up, setUp] = useState<Uploaded | null>(() => (restored?.d.documentId
    ? { ...restored.kept, documentId: restored.d.documentId, pageCount: restored.d.pageCount, fileName: restored.d.fileName } : null));
  const [opts, setOpts] = useState<Options>(() => (restored?.d.documentId
    ? { copies: restored.d.copies, color: restored.d.color, duplex: restored.d.duplex, pageRange: restored.d.pageRange }
    : { copies: 1, color: false, duplex: false, pageRange: null }));
  const [somePages, setSomePages] = useState(() => !!restored?.d.documentId && restored.d.pageRange !== null);
  const [peek, setPeek] = useState(false);
  const [quote, setQuote] = useState<Schemas["QuoteResponse"] | null>(null);
  const draft = useRef<Kept | null>(restored?.kept ?? null);
  const working = useRef(false);            // one action at a time, however fast the button is tapped

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    Promise.all([api.getShop(shopCode), api.getRates(shopCode).catch(() => null)])
      .then(([s, r]) => { if (alive) { setShop(s); setRates(r); rememberShop({ code: s.code, name: s.name }); } })
      .catch((e) => alive && setLoadError({ message: message(e), retry: code(e) !== "shop_not_found" }));
    return () => { alive = false; };
  }, [shopCode, attempt]);

  // Once the first screen is up and a file is about to be chosen, fetch the PDF reader in the background (see preview.tsx).
  const awaitingFile = !!shop?.accepting_orders && !up;
  useEffect(() => (awaitingFile ? warmPdfReaderWhenIdle() : undefined), [awaitingFile]);

  // A message must be seen: on a short phone it can appear below the screen, or behind the price bar.
  const alertAt = useRef<HTMLParagraphElement>(null);
  useEffect(() => { alertAt.current?.scrollIntoView?.({ block: "nearest" }); }, [error, unprintable]);

  function startOver(why: string | null) {
    clearDraft(); draft.current = null;
    setUp(null); setQuote(null); setFile(null); setPeek(false); setError(why);
  }

  // A restored file is shown at once and checked in the background: if the server no longer has it, say so.
  useEffect(() => {
    if (!restored?.d.documentId) return;
    let alive = true;
    api.getOrder(restored.kept.orderId, restored.kept.secret)
      .then((o) => { if (alive && o.status !== "draft") startOver(null); })
      .catch((e) => { if (alive && code(e) === "order_not_found") startOver("Your file is no longer kept. Please choose it again."); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restored]);

  // Remember where this tab is, for a refresh.
  useEffect(() => {
    const kept = up ?? draft.current;
    if (!kept) return;
    saveDraft({ shopCode, orderId: kept.orderId, shortCode: kept.shortCode, documentId: up?.documentId ?? null, pageCount: up?.pageCount ?? 0,
      fileName: up?.fileName ?? "", copies: Number.isFinite(opts.copies) ? opts.copies : 1, color: opts.color, duplex: opts.duplex, pageRange: opts.pageRange });
  }, [shopCode, up, opts]);

  const check = useMemo(() => (up ? estimate(up.pageCount, opts, rates ?? NO_RATES) : null), [up, rates, opts]);
  const est = rates ? check : null;
  // what the whole job would cost with one setting changed, shown under each choice
  const priceWith = (change: Partial<Options>): string | undefined => {
    if (!up || !rates) return undefined;
    const e = estimate(up.pageCount, { ...opts, ...change }, rates);
    // while the page range or the copies cannot be priced, the line under each choice stays (empty), so nothing jumps under the thumb that is typing
    return e.ok ? rupees(e.amountPaise) : String.fromCharCode(160);   // a no-break space
  };

  function choose(f: File | null) {
    setError(null); setUp(null); setQuote(null); setFile(null); setUnprintable(null);
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) { setError("Only PDF files can be printed."); return; }
    if (f.size === 0) { setError("This file is empty. Choose another PDF."); return; }
    if (f.size > MAX_BYTES) { setError("The file is larger than 25 MB."); return; }
    setFile(f);
  }

  function drop(e: DragEvent) {
    e.preventDefault(); setDragging(false);
    if (!busy) choose(e.dataTransfer.files?.[0] ?? null);
  }

  /** Runs one step of the flow; a second tap while it runs does nothing. */
  async function step(label: string, work: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setError(null); setBusy(label);
    try { await work(); } catch (e) {
      if (FILE_GONE.has(code(e)) && up) startOver("Your file is no longer kept. Please choose it again.");
      else setError(message(e));
    } finally { working.current = false; setBusy(null); setProgress(null); }
  }

  const upload = () => step("Checking your file…", async () => {
    if (!file) return;
    const seen = await inspectPdf(file);
    if (seen.kind === "encrypted" || seen.kind === "invalid") { setUnprintable(seen.kind); return; }
    // ("unknown" goes on: this browser could not read PDFs at all, and the server checks every file anyway.)
    // One order per visit: trying again after a failed upload reuses it instead of starting (and counting) a new one.
    const doc = { file_name: file.name.slice(0, 255), byte_size: file.size, content_type: "application/pdf" };
    let order = draft.current;
    let reg: Schemas["RegisterDocumentResponse"] | null = null;
    if (order) {
      setBusy("Uploading…");
      try { reg = await api.registerDocument(order.orderId, order.secret, doc); }
      catch (e) {
        if (!ORDER_UNUSABLE.has(code(e))) throw e;
        order = null;                                           // the kept order ran out: start a fresh one below
      }
    }
    if (!order) {
      setBusy("Starting your order…");
      const made = await api.createOrder(shopCode);
      order = draft.current = { orderId: made.order_id, secret: made.order_secret, shortCode: made.short_code };
      saveSecret(order.orderId, order.secret);
      saveDraft({ shopCode, ...order, documentId: null, pageCount: 0, fileName: "", copies: 1, color: false, duplex: false, pageRange: null });
    }
    setBusy("Uploading…");
    reg ??= await api.registerDocument(order.orderId, order.secret, doc);
    setProgress(0);
    await uploadPdf(reg.upload_url, reg.upload_headers, file, setProgress);
    setProgress(1);
    setBusy("Checking the upload…");
    const fin = await api.finalizeDocument(order.orderId, reg.document_id, order.secret);
    setUp({ ...order, documentId: reg.document_id, pageCount: fin.page_count, fileName: file.name });
  });

  const seePrice = () => step("Calculating the price…", async () => {
    if (!up) return;
    setQuote(await api.createQuote(up.orderId, up.secret, {
      items: [{ document_id: up.documentId, options: { copies: opts.copies, color: opts.color, duplex: opts.duplex, page_range: opts.pageRange?.trim() || null } }],
    }));
  });

  const send = () => step("Sending to the shop…", async () => {
    if (!up || !quote) return;
    try { await api.submitOrder(up.orderId, up.secret, quote.quote_id); }
    catch (e) {
      if (code(e) === "quote_not_found") setQuote(null);
      // "already submitted" means an earlier tap did reach the shop although its answer never arrived: show that order
      if (code(e) !== "order_not_draft") throw e;
    }
    clearDraft();
    rememberOrder({ id: up.orderId, code: up.shortCode, shopCode, shopName: shop?.name ?? shopCode });
    navigate(`/o/${up.orderId}`);
  });

  if (loadError) {
    return (
      <main><TopBar /><div className="card center">
        <h1>AutoPrint</h1><p role="alert" className="error">{loadError.message}</p>
        {loadError.retry && <button className="primary" onClick={() => setAttempt((n) => n + 1)}>Try again</button>}
        <a className="button" href="/">{loadError.retry ? "Type a shop code" : "Try another shop code"}</a>
      </div></main>
    );
  }
  if (!shop) return <main aria-busy="true"><TopBar /><div className="skeleton head-shape" /><div className="skeleton steps-shape" /><div className="skeleton drop-shape" /><p className="sr-only">Loading…</p></main>;
  if (!shop.accepting_orders) return <main><TopBar /><div className="card center"><h1>{shop.name}</h1><p role="alert" className="error">This shop is not taking orders right now.</p><a className="button" href="/">Try another shop code</a></div></main>;

  const percent = progress === null ? null : Math.round(progress * 100);
  return (
    <main className={up ? "with-bar" : ""}>
      <TopBar />
      <header className="shop-head">
        <p className="eyebrow">Print at</p>
        <h1>{shop.name}</h1>
        <span className={`pill ${shop.agent_online ? "ok" : "warn"}`}><i className="dot" />{shop.agent_online ? "Open for prints" : "Shop computer offline"}</span>
      </header>
      {!shop.agent_online && (
        <p className="note" role="status">The shop's printer computer looks offline. You can still send your file; it will wait for the shop.</p>
      )}
      <Steps labels={["File", "Settings", "Send"]} current={!up ? 1 : !quote ? 2 : 3} />

      {!up && (
        <section className="rise">
          <label className={`drop${file ? " has" : ""}${dragging ? " over" : ""}`}
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop} onPointerDown={warmPdfReader}>
            <input type="file" accept="application/pdf,.pdf" aria-label="Choose a PDF to print" onChange={(e) => choose(e.target.files?.[0] ?? null)} disabled={!!busy} />
            <span className="drop-icon">{file ? <Icon.file size={28} /> : <Icon.upload size={28} />}</span>
            {file
              ? <><strong className="ellipsis">{file.name}</strong><small>{fileSize(file.size)} · tap to choose another</small></>
              : <><strong>Choose a PDF</strong><small>Tap to pick a file from your phone</small></>}
          </label>
          {(error || unprintable) && <p ref={alertAt} role="alert" className="error">{error ?? PDF_PROBLEM[unprintable!]}</p>}
          {file && !unprintable && <PdfPreview file={file} onProblem={setUnprintable} />}
          {file && !unprintable && (
            <button className="primary big" onClick={upload} disabled={!!busy}>
              {busy ? <><i className="spinner" />{busy}{percent !== null && percent < 100 ? ` ${percent}%` : ""}</> : <>Continue<Icon.arrow size={20} /></>}
            </button>
          )}
          {percent !== null && <div className="progress" role="progressbar" aria-label="Upload" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{ transform: `scaleX(${progress})` }} /></div>}
          {!file && !error && <p className="hint">No app and no account. You see the price before anything is sent.</p>}
          {!file && <YourOrders shopCode={shopCode} />}
        </section>
      )}

      {up && (
        <section className="rise">
          <div className="card filecard">
            <span className="file-badge"><Icon.file size={22} /></span>
            <div>
              <strong className="ellipsis">{up.fileName}</strong>
              <p className="meta"><span>{up.pageCount} {up.pageCount === 1 ? "page" : "pages"}</span> · ready</p>
            </div>
            <span className="tick"><Icon.check size={16} /></span>
          </div>
          <div className="file-actions">
            {/* rendered only once opened: the preview sizes itself to the space it is given */}
            {file && <details className="peek" onToggle={(e) => setPeek(e.currentTarget.open)}><summary>Look at the file</summary>{peek && <PdfPreview file={file} />}</details>}
            <button className="link" onClick={() => { const kept = draft.current; startOver(null); draft.current = kept; }} disabled={!!busy}>Choose another file</button>
          </div>

          <fieldset className="card options" disabled={!!busy || !!quote} aria-labelledby="print-settings">
            <h2 id="print-settings">Print settings</h2>
            <Segmented label="Colour" value={opts.color ? "color" : "bw"} onChange={(v) => setOpts({ ...opts, color: v === "color" })}
                       options={[{ value: "bw", label: "Black & white", hint: priceWith({ color: false }) }, { value: "color", label: "Colour", hint: priceWith({ color: true }) }]} />
            <Segmented label="Sides" value={opts.duplex ? "duplex" : "simplex"} onChange={(v) => setOpts({ ...opts, duplex: v === "duplex" })}
                       options={[{ value: "simplex", label: "One side", hint: priceWith({ duplex: false }) }, { value: "duplex", label: "Both sides", hint: priceWith({ duplex: true }) }]} />
            <Stepper label="Copies" value={opts.copies} min={1} max={100} onChange={(copies) => setOpts({ ...opts, copies })} />
            <Segmented label="Pages" value={somePages ? "some" : "all"}
                       onChange={(v) => { setSomePages(v === "some"); if (v === "all") setOpts({ ...opts, pageRange: null }); }}
                       options={[{ value: "all", label: "All pages" }, { value: "some", label: "Some pages" }]} />
            {somePages && (
              <label className="field">
                <span className="field-label">Which pages? <small>for example 1-3, 5</small></span>
                <input type="text" inputMode="text" autoFocus value={opts.pageRange ?? ""} placeholder={`1-${up.pageCount}`}
                       onChange={(e) => setOpts({ ...opts, pageRange: e.target.value || null })} />
              </label>
            )}
          </fieldset>

          {error && <p ref={alertAt} role="alert" className="error">{error}</p>}

          <div className="bar">
            {!quote ? (
              <>
                <div className="bar-price">
                  {check && !check.ok && <p role="alert" className="error">{check.code === "invalid_page_range" ? `Check the page range: this file has ${up.pageCount} ${up.pageCount === 1 ? "page" : "pages"}.` : "Copies must be between 1 and 100."}</p>}
                  {est?.ok && <p className="estimate">About <strong key={est.amountPaise} className="swap">{rupees(est.amountPaise)}</strong> <small>({est.printedSides} sides × {rupees(est.paisePerSide)})</small></p>}
                  {!rates && check?.ok && <p className="meta">The price is shown in the next step.</p>}
                </div>
                <button className="primary" onClick={seePrice} disabled={!!busy || !check?.ok}>{busy ? <><i className="spinner" />{busy}</> : "See exact price"}</button>
              </>
            ) : (
              <div className="quote rise" aria-live="polite">
                <div>
                  <p className="total">{rupees(quote.total_paise)}</p>
                  <p className="meta">{quote.items[0].printed_sides} sides × {rupees(quote.items[0].paise_per_side)} · pay at the counter</p>
                </div>
                <button className="primary big" onClick={send} disabled={!!busy}>{busy ? <><i className="spinner" />{busy}</> : <>Send to shop<Icon.arrow size={20} /></>}</button>
                <button className="link" onClick={() => setQuote(null)} disabled={!!busy}>Change settings</button>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
