// The counter QR opens /s/<SHOP CODE>. One screen walks the customer from file to submitted order.
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api, uploadPdf, type Schemas } from "../api";
import { estimate, rupees, type Options } from "../estimate";
import { PdfPreview, readPageCount } from "../preview";
import { saveSecret } from "../store";
import { rememberShop } from "../shopCode";
import { Icon, Segmented, Stepper, Steps, TopBar, fileSize } from "../ui";

const MAX_BYTES = 26_214_400;
// answers that mean a kept draft order cannot take another file
const ORDER_UNUSABLE = new Set(["order_not_found", "order_expired", "order_not_draft", "too_many_documents"]);

type Uploaded = { orderId: string; secret: string; documentId: string; pageCount: number; fileName: string };

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}

export default function ShopPage() {
  const { shopCode = "" } = useParams();
  const navigate = useNavigate();
  const [shop, setShop] = useState<Schemas["ShopPublic"] | null>(null);
  const [rates, setRates] = useState<Schemas["RateCardPublic"] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [up, setUp] = useState<Uploaded | null>(null);
  const [opts, setOpts] = useState<Options>({ copies: 1, color: false, duplex: false, pageRange: null });
  const [somePages, setSomePages] = useState(false);
  const [peek, setPeek] = useState(false);
  const [quote, setQuote] = useState<Schemas["QuoteResponse"] | null>(null);
  const draft = useRef<{ shopCode: string; order: Schemas["CreateOrderResponse"] } | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([api.getShop(shopCode), api.getRates(shopCode).catch(() => null)])
      .then(([s, r]) => { if (alive) { setShop(s); setRates(r); rememberShop({ code: s.code, name: s.name }); } })
      .catch((e) => alive && setLoadError(message(e)));
    return () => { alive = false; };
  }, [shopCode]);

  const est = useMemo(() => (up && rates ? estimate(up.pageCount, opts, rates) : null), [up, rates, opts]);
  // what the whole job would cost with one setting changed, shown under each choice
  const priceWith = (change: Partial<Options>): string | undefined => {
    if (!up || !rates) return undefined;
    const e = estimate(up.pageCount, { ...opts, ...change }, rates);
    return e.ok ? rupees(e.amountPaise) : undefined;
  };

  async function choose(f: File | null) {
    setError(null); setUp(null); setQuote(null); setFile(null);
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) { setError("Only PDF files can be printed."); return; }
    if (f.size > MAX_BYTES) { setError("The file is larger than 25 MB."); return; }
    setFile(f);
  }

  function drop(e: DragEvent) {
    e.preventDefault(); setDragging(false);
    if (!busy) void choose(e.dataTransfer.files?.[0] ?? null);
  }

  async function upload() {
    if (!file) return;
    setError(null);
    try {
      setBusy("Checking your file…");
      const pageCount = await readPageCount(file).catch(() => 0);
      if (pageCount < 1) throw new ApiError("pdf_unreadable", "This PDF could not be read. Try saving or exporting it again.");
      // One order per visit: trying again after a failed upload reuses it instead of starting (and counting) a new one.
      const doc = { file_name: file.name, byte_size: file.size, content_type: "application/pdf" };
      let order = draft.current?.shopCode === shopCode ? draft.current.order : null;
      let reg: Schemas["RegisterDocumentResponse"] | null = null;
      if (order) {
        setBusy("Uploading…");
        try { reg = await api.registerDocument(order.order_id, order.order_secret, doc); }
        catch (e) {
          if (!(e instanceof ApiError) || !ORDER_UNUSABLE.has(e.code)) throw e;
          order = null;                                           // the kept order ran out: start a fresh one below
        }
      }
      if (!order) {
        setBusy("Starting your order…");
        order = await api.createOrder(shopCode);
        draft.current = { shopCode, order };
        saveSecret(order.order_id, order.order_secret);
      }
      setBusy("Uploading…");
      reg ??= await api.registerDocument(order.order_id, order.order_secret, doc);
      setProgress(0);
      await uploadPdf(reg.upload_url, reg.upload_headers, file, setProgress);
      setProgress(1);
      setBusy("Checking the upload…");
      const fin = await api.finalizeDocument(order.order_id, reg.document_id, order.order_secret);
      setUp({ orderId: order.order_id, secret: order.order_secret, documentId: reg.document_id, pageCount: fin.page_count, fileName: file.name });
    } catch (e) { setError(message(e)); } finally { setBusy(null); setProgress(null); }
  }

  async function seePrice() {
    if (!up) return;
    setError(null); setBusy("Calculating the price…");
    try {
      setQuote(await api.createQuote(up.orderId, up.secret, {
        items: [{ document_id: up.documentId, options: { copies: opts.copies, color: opts.color, duplex: opts.duplex, page_range: opts.pageRange?.trim() || null } }],
      }));
    } catch (e) { setError(message(e)); } finally { setBusy(null); }
  }

  async function send() {
    if (!up || !quote) return;
    setError(null); setBusy("Sending to the shop…");
    try {
      await api.submitOrder(up.orderId, up.secret, quote.quote_id);
      navigate(`/o/${up.orderId}`);
    } catch (e) { setError(message(e)); setBusy(null); }
  }

  if (loadError) return <main><TopBar /><div className="card center"><h1>AutoPrint</h1><p role="alert" className="error">{loadError}</p><a className="button" href="/">Try another shop code</a></div></main>;
  if (!shop) return <main aria-busy="true"><TopBar /><div className="skeleton title" /><div className="skeleton block" /><p className="sr-only">Loading…</p></main>;
  if (!shop.accepting_orders) return <main><TopBar /><div className="card center"><h1>{shop.name}</h1><p role="alert" className="error">This shop is not taking orders right now.</p></div></main>;

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
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
            <input type="file" accept="application/pdf,.pdf" onChange={(e) => choose(e.target.files?.[0] ?? null)} disabled={!!busy} />
            <span className="drop-icon">{file ? <Icon.file size={28} /> : <Icon.upload size={28} />}</span>
            {file
              ? <><strong className="ellipsis">{file.name}</strong><small>{fileSize(file.size)} · tap to choose another</small></>
              : <><strong>Choose a PDF</strong><small>Tap to pick a file from your phone</small></>}
          </label>
          {file && <PdfPreview file={file} />}
          {file && (
            <button className="primary big" onClick={upload} disabled={!!busy}>
              {busy ? <><i className="spinner" />{busy}</> : <>Continue<Icon.arrow size={20} /></>}
            </button>
          )}
          {progress !== null && <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
          {!file && !error && <p className="hint">No app and no account. You see the price before anything is sent.</p>}
        </section>
      )}

      {up && file && (
        <section className="rise">
          <div className="card filecard">
            <span className="file-badge"><Icon.file size={22} /></span>
            <div>
              <strong className="ellipsis">{up.fileName}</strong>
              <p className="meta"><span>{up.pageCount} {up.pageCount === 1 ? "page" : "pages"}</span> · ready</p>
            </div>
            <span className="tick"><Icon.check size={16} /></span>
          </div>
          {/* rendered only once opened: the preview sizes itself to the space it is given */}
          <details className="peek" onToggle={(e) => setPeek(e.currentTarget.open)}><summary>Look at the file</summary>{peek && <PdfPreview file={file} />}</details>

          <fieldset className="card options" disabled={!!busy || !!quote}>
            <legend>Print settings</legend>
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

          {error && <p role="alert" className="error">{error}</p>}

          <div className="bar">
            {!quote ? (
              <>
                <div className="bar-price">
                  {est && !est.ok && <p role="alert" className="error">{est.code === "invalid_page_range" ? "Check the page range." : "Copies must be between 1 and 100."}</p>}
                  {est?.ok && <p className="estimate">About <strong>{rupees(est.amountPaise)}</strong> <small>({est.printedSides} sides × {rupees(est.paisePerSide)})</small></p>}
                </div>
                <button className="primary" onClick={seePrice} disabled={!!busy || !est?.ok}>{busy ? <><i className="spinner" />{busy}</> : "See exact price"}</button>
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

      {!up && error && <p role="alert" className="error">{error}</p>}
    </main>
  );
}
