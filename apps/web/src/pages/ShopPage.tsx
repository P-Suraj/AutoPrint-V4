// The counter QR opens /s/<SHOP CODE>. One screen walks the customer from file to submitted order.
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api, uploadPdf, type Schemas } from "../api";
import { estimate, rupees, type Options } from "../estimate";
import { PdfPreview, readPageCount } from "../preview";
import { saveSecret } from "../store";
import { rememberShop } from "../shopCode";

const MAX_BYTES = 26_214_400;

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
  const [error, setError] = useState<string | null>(null);
  const [up, setUp] = useState<Uploaded | null>(null);
  const [opts, setOpts] = useState<Options>({ copies: 1, color: false, duplex: false, pageRange: null });
  const [quote, setQuote] = useState<Schemas["QuoteResponse"] | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([api.getShop(shopCode), api.getRates(shopCode).catch(() => null)])
      .then(([s, r]) => { if (alive) { setShop(s); setRates(r); rememberShop({ code: s.code, name: s.name }); } })
      .catch((e) => alive && setLoadError(message(e)));
    return () => { alive = false; };
  }, [shopCode]);

  const est = useMemo(() => (up && rates ? estimate(up.pageCount, opts, rates) : null), [up, rates, opts]);

  async function choose(f: File | null) {
    setError(null); setUp(null); setQuote(null); setFile(null);
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) { setError("Only PDF files can be printed."); return; }
    if (f.size > MAX_BYTES) { setError("The file is larger than 25 MB."); return; }
    setFile(f);
  }

  async function upload() {
    if (!file) return;
    setError(null);
    try {
      setBusy("Checking your file…");
      const pageCount = await readPageCount(file).catch(() => 0);
      if (pageCount < 1) throw new ApiError("pdf_unreadable", "This PDF could not be read. Try saving or exporting it again.");
      setBusy("Starting your order…");
      const order = await api.createOrder(shopCode);
      saveSecret(order.order_id, order.order_secret);
      setBusy("Uploading…");
      const reg = await api.registerDocument(order.order_id, order.order_secret,
        { file_name: file.name, byte_size: file.size, content_type: "application/pdf" });
      await uploadPdf(reg.upload_url, reg.upload_headers, file);
      setBusy("Checking the upload…");
      const fin = await api.finalizeDocument(order.order_id, reg.document_id, order.order_secret);
      setUp({ orderId: order.order_id, secret: order.order_secret, documentId: reg.document_id, pageCount: fin.page_count, fileName: file.name });
    } catch (e) { setError(message(e)); } finally { setBusy(null); }
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

  if (loadError) return <main><h1>AutoPrint</h1><p role="alert" className="error">{loadError}</p><a href="/">Try another shop code</a></main>;
  if (!shop) return <main><h1>AutoPrint</h1><p>Loading…</p></main>;
  if (!shop.accepting_orders) return <main><h1>{shop.name}</h1><p role="alert" className="error">This shop is not taking orders right now.</p></main>;

  return (
    <main>
      <header><p className="eyebrow">Print at</p><h1>{shop.name}</h1></header>
      {!shop.agent_online && (
        <p className="note" role="status">The shop's printer computer looks offline. You can still send your file; it will wait for the shop.</p>
      )}

      {!up && (
        <section>
          <label className="file">
            <span>Choose a PDF</span>
            <input type="file" accept="application/pdf,.pdf" onChange={(e) => choose(e.target.files?.[0] ?? null)} disabled={!!busy} />
          </label>
          {file && <PdfPreview file={file} />}
          {file && <button className="primary" onClick={upload} disabled={!!busy}>{busy ?? "Continue"}</button>}
        </section>
      )}

      {up && file && (
        <section>
          <PdfPreview file={file} />
          <p className="meta">{up.fileName} · {up.pageCount} {up.pageCount === 1 ? "page" : "pages"}</p>
          <fieldset disabled={!!busy || !!quote}>
            <legend>Print settings</legend>
            <label>Colour
              <select value={opts.color ? "color" : "bw"} onChange={(e) => setOpts({ ...opts, color: e.target.value === "color" })}>
                <option value="bw">Black &amp; white</option><option value="color">Colour</option>
              </select>
            </label>
            <label>Sides
              <select value={opts.duplex ? "duplex" : "simplex"} onChange={(e) => setOpts({ ...opts, duplex: e.target.value === "duplex" })}>
                <option value="simplex">Single-sided</option><option value="duplex">Double-sided</option>
              </select>
            </label>
            <label>Copies
              <input type="number" min={1} max={100} value={opts.copies}
                onChange={(e) => setOpts({ ...opts, copies: Math.trunc(Number(e.target.value)) })} />
            </label>
            <label>Pages <small>(blank = all, or e.g. 1-3, 5)</small>
              <input type="text" inputMode="text" value={opts.pageRange ?? ""} placeholder="All pages"
                onChange={(e) => setOpts({ ...opts, pageRange: e.target.value || null })} />
            </label>
          </fieldset>

          {est && !est.ok && <p role="alert" className="error">{est.code === "invalid_page_range" ? "Check the page range." : "Copies must be between 1 and 100."}</p>}
          {est?.ok && !quote && <p className="estimate">About <strong>{rupees(est.amountPaise)}</strong> <small>({est.printedSides} sides × {rupees(est.paisePerSide)})</small></p>}
          {!quote && <button className="primary" onClick={seePrice} disabled={!!busy || !est?.ok}>{busy ?? "See exact price"}</button>}

          {quote && (
            <div className="quote" aria-live="polite">
              <p className="total">{rupees(quote.total_paise)}</p>
              <p className="meta">{quote.items[0].printed_sides} sides × {rupees(quote.items[0].paise_per_side)} · pay at the counter</p>
              <button className="primary" onClick={send} disabled={!!busy}>{busy ?? "Send to shop"}</button>
              <button className="link" onClick={() => setQuote(null)} disabled={!!busy}>Change settings</button>
            </div>
          )}
        </section>
      )}

      {error && <p role="alert" className="error">{error}</p>}
    </main>
  );
}
