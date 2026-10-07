// The counter QR opens /s/<SHOP CODE>. One screen walks the customer from files to submitted order.
// An order can hold several PDFs; each has its own print settings and becomes its own job at the shop.
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api, uploadPdf, type Schemas } from "../api";
import { estimate, rupees, type Estimate, type Options, type Rates } from "../estimate";
import { YourOrders } from "../orders";
import { PDF_PROBLEM, PdfPreview, inspectPdf, warmPdfReader, warmPdfReaderWhenIdle, type PdfProblem } from "../preview";
import { clearDraft, loadDraft, loadSecret, rememberOrder, saveDraft, saveSecret } from "../store";
import { rememberShop } from "../shopCode";
import { Icon, Segmented, Stepper, Steps, TopBar, fileSize } from "../ui";

const MAX_BYTES = 26_214_400;
const MAX_FILES = 20;                       // the server's limit for one order
// answers that mean a kept draft order cannot take another file
const ORDER_UNUSABLE = new Set(["order_not_found", "order_expired", "order_not_draft", "too_many_documents"]);
// answers that mean the uploaded files are no longer there to be priced or sent (an unsent file is kept for an hour)
const FILE_GONE = new Set(["order_not_found", "order_expired", "document_not_ready", "document_not_found"]);
const GONE = "Your files are no longer kept. Please choose them again.";
// with no price list from the server the settings can still be checked; the price then comes from the exact quote
const NO_RATES: Rates = { bw: { simplex: [], duplex: [] }, color: { simplex: [], duplex: [] } };

type Kept = { orderId: string; secret: string; shortCode: string };
/** One uploaded file and how it is to be printed. `somePages` is only which of the two "Pages" choices is shown. */
type Doc = { documentId: string; pageCount: number; fileName: string; opts: Options; somePages: boolean };
type LoadError = { message: string; retry: boolean };

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}
const code = (e: unknown) => (e instanceof ApiError ? e.code : "");
const pagesText = (n: number) => `${n} ${n === 1 ? "page" : "pages"}`;

/** Why this file cannot be sent, or null. Checked before anything is uploaded. */
function refusal(f: File): string | null {
  if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) return "Only PDF files can be printed.";
  if (f.size === 0) return "This file is empty. Choose another PDF.";
  if (f.size > MAX_BYTES) return "The file is larger than 25 MB.";
  return null;
}

// A different shop code is a different visit: nothing chosen for one shop may leak into another.
export default function ShopPage() {
  const { shopCode = "" } = useParams();
  return <ShopFlow key={shopCode} shopCode={shopCode} />;
}

function ShopFlow({ shopCode }: { shopCode: string }) {
  const navigate = useNavigate();
  // What this tab was doing before a refresh or the back button (see store.ts): the uploaded files are not asked for again.
  const restored = useMemo(() => {
    const d = loadDraft(shopCode);
    const secret = d ? loadSecret(d.orderId) : null;
    return d && secret ? { d, kept: { orderId: d.orderId, secret, shortCode: d.shortCode } } : null;
  }, [shopCode]);
  const [shop, setShop] = useState<Schemas["ShopPublic"] | null>(null);
  const [rates, setRates] = useState<Schemas["RateCardPublic"] | null>(null);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [picked, setPicked] = useState<File[]>([]);                          // chosen on the first screen, not uploaded yet
  const [unprintable, setUnprintable] = useState<PdfProblem | null>(null);   // the chosen file cannot be printed: say why, offer nothing else
  const [busy, setBusy] = useState<string | null>(null);
  const [busyAt, setBusyAt] = useState<"files" | "bar">("files");            // which control shows the spinner
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState<Doc[]>(() => (restored?.d.docs ?? []).map((d) => ({
    documentId: d.documentId, pageCount: d.pageCount, fileName: d.fileName, somePages: d.pageRange !== null,
    opts: { copies: d.copies, color: d.color, duplex: d.duplex, pageRange: d.pageRange },
  })));
  const [openId, setOpenId] = useState<string | null>(() => restored?.d.docs[0]?.documentId ?? null);
  const [quote, setQuote] = useState<Schemas["QuoteResponse"] | null>(null);
  const draft = useRef<Kept | null>(restored?.kept ?? null);
  const files = useRef(new Map<string, File>());   // the files as chosen, for "Look at the file"; gone after a refresh
  const working = useRef(false);                   // one action at a time, however fast the button is tapped
  const have = useRef(0);                          // how many files are uploaded, readable inside a running step
  have.current = docs.length;

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    Promise.all([api.getShop(shopCode), api.getRates(shopCode).catch(() => null)])
      .then(([s, r]) => { if (alive) { setShop(s); setRates(r); rememberShop({ code: s.code, name: s.name }); } })
      .catch((e) => alive && setLoadError({ message: message(e), retry: code(e) !== "shop_not_found" }));
    return () => { alive = false; };
  }, [shopCode, attempt]);

  // A shop that has said it does not print in colour: no file may ask for it, whatever was chosen before.
  const colourOk = shop?.color_available !== false;
  useEffect(() => {
    if (!colourOk) setDocs((prev) => (prev.some((d) => d.opts.color) ? prev.map((d) => ({ ...d, opts: { ...d.opts, color: false } })) : prev));
  }, [colourOk, docs]);

  // Once the first screen is up and a file is about to be chosen, fetch the PDF reader in the background (see preview.tsx).
  const awaitingFile = !!shop?.accepting_orders && docs.length === 0;
  useEffect(() => (awaitingFile ? warmPdfReaderWhenIdle() : undefined), [awaitingFile]);

  // A message must be seen: on a short phone it can appear below the screen, or behind the price bar.
  const alertAt = useRef<HTMLParagraphElement>(null);
  useEffect(() => { alertAt.current?.scrollIntoView?.({ block: "nearest" }); }, [error, unprintable]);

  function startOver(why: string | null) {
    clearDraft(); draft.current = null; files.current.clear();
    setDocs([]); setOpenId(null); setQuote(null); setPicked([]); setError(why);
  }

  // Restored files are shown at once and checked in the background: if the server no longer has them, say so.
  useEffect(() => {
    if (!restored?.d.docs.length) return;
    let alive = true;
    api.getOrder(restored.kept.orderId, restored.kept.secret)
      .then((o) => { if (alive && o.status !== "draft") startOver(null); })
      .catch((e) => { if (alive && code(e) === "order_not_found") startOver(GONE); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restored]);

  // Remember where this tab is, for a refresh.
  useEffect(() => {
    const kept = draft.current;
    if (!kept) return;
    saveDraft({ shopCode, orderId: kept.orderId, shortCode: kept.shortCode, docs: docs.map((d) => ({
      documentId: d.documentId, pageCount: d.pageCount, fileName: d.fileName,
      copies: Number.isFinite(d.opts.copies) ? d.opts.copies : 1, color: d.opts.color, duplex: d.opts.duplex, pageRange: d.opts.pageRange })) });
  }, [shopCode, docs]);

  const checks = useMemo(() => docs.map((d) => estimate(d.pageCount, d.opts, rates ?? NO_RATES)), [docs, rates]);
  const firstBad = checks.findIndex((c) => !c.ok);
  const allOk = docs.length > 0 && firstBad < 0;
  const totals = useMemo(() => checks.reduce((t, c) => (c.ok ? { paise: t.paise + c.amountPaise, sides: t.sides + c.printedSides } : t), { paise: 0, sides: 0 }), [checks]);
  const exact = useMemo(() => new Map((quote?.items ?? []).map((i) => [i.document_id, i.amount_paise])), [quote]);

  /** The files that may be sent, or null after saying why not. */
  function accept(list: File[]): File[] | null {
    if (have.current + list.length > MAX_FILES) { setError(`One order can have at most ${MAX_FILES} files.`); return null; }
    for (const f of list) {
      const why = refusal(f);
      if (why) { setError(list.length > 1 ? `${f.name}: ${why}` : why); return null; }
    }
    return list;
  }

  function choose(list: File[]) {
    setError(null); setQuote(null); setPicked([]); setUnprintable(null);
    if (list.length) setPicked(accept(list) ?? []);
  }

  function drop(e: DragEvent) {
    e.preventDefault(); setDragging(false);
    if (!busy) choose([...(e.dataTransfer.files ?? [])]);
  }

  /** Runs one step of the flow; a second tap while it runs does nothing. */
  async function step(label: string, at: "files" | "bar", work: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setError(null); setBusy(label); setBusyAt(at);
    try { await work(); } catch (e) {
      if (FILE_GONE.has(code(e)) && have.current > 0) startOver(GONE);
      else setError(message(e));
    } finally { working.current = false; setBusy(null); setProgress(null); }
  }

  /** Uploads the files one after another. A file that fails stops the rest; the ones before it are kept. */
  const upload = (list: File[]) => step("Checking your file…", "files", async () => {
    const many = list.length > 1;
    const say = (what: string, i: number) => setBusy(many ? `${what} ${i + 1} of ${list.length}…` : `${what}…`);
    try {
      for (let i = 0; i < list.length; i++) {
        const file = list[i];
        try {
          if (many) say("Checking file", i);
          const seen = await inspectPdf(file);
          if (seen.kind === "encrypted" || seen.kind === "invalid") {
            if (!many && have.current === 0) { setUnprintable(seen.kind); return; }
            throw new ApiError("unprintable", PDF_PROBLEM[seen.kind]);
          }
          // ("unknown" goes on: this browser could not read PDFs at all, and the server checks every file anyway.)
          // One order per visit: trying again after a failed upload reuses it instead of starting (and counting) a new one.
          const doc = { file_name: file.name.slice(0, 255), byte_size: file.size, content_type: "application/pdf" };
          let order = draft.current;
          let reg: Schemas["RegisterDocumentResponse"] | null = null;
          if (order) {
            say("Uploading", i);
            try { reg = await api.registerDocument(order.orderId, order.secret, doc); }
            catch (e) {
              if (!ORDER_UNUSABLE.has(code(e))) throw e;
              if (have.current > 0) {
                // the files already here belong to that order: a fresh order could not send them
                if (code(e) === "too_many_documents") throw e;
                startOver(GONE);
                return;
              }
              order = null;                                         // the kept order ran out: start a fresh one below
            }
          }
          if (!order) {
            setBusy("Starting your order…");
            const made = await api.createOrder(shopCode);
            order = draft.current = { orderId: made.order_id, secret: made.order_secret, shortCode: made.short_code };
            saveSecret(order.orderId, order.secret);
            saveDraft({ shopCode, ...order, docs: [] });
          }
          say("Uploading", i);
          reg ??= await api.registerDocument(order.orderId, order.secret, doc);
          setProgress(0);
          await uploadPdf(reg.upload_url, reg.upload_headers, file, setProgress);
          setProgress(1);
          say("Checking the upload", i);
          const fin = await api.finalizeDocument(order.orderId, reg.document_id, order.secret);
          setProgress(null);
          const id = reg.document_id;
          files.current.set(id, file);
          have.current += 1;
          setDocs((prev) => [...prev, { documentId: id, pageCount: fin.page_count, fileName: file.name, somePages: false,
            opts: { copies: 1, color: false, duplex: false, pageRange: null } }]);
          setOpenId((open) => open ?? id);
        } catch (e) {
          if (many && e instanceof ApiError) throw new ApiError(e.code, `${file.name}: ${e.message}`, e.status);
          throw e;
        }
      }
    } finally {
      if (have.current > 0) setPicked([]);                          // the settings screen takes over
    }
  });

  const addMore = (list: File[]) => {
    if (working.current || list.length === 0) return;
    setError(null);
    const ok = accept(list);
    if (ok) void upload(ok);
  };

  function change(id: string, next: Partial<Pick<Doc, "opts" | "somePages">>) {
    setDocs((prev) => prev.map((d) => (d.documentId === id ? { ...d, ...next } : d)));
  }

  function remove(id: string) {
    files.current.delete(id);
    setError(null); setQuote(null);
    const left = docs.filter((d) => d.documentId !== id);
    setDocs(left);
    if (openId === id || left.length === 1) setOpenId(left[0]?.documentId ?? null);
  }

  /** Colour, sides and copies of one file for every file. Not the page range: that belongs to one document. */
  function sameForAll(from: Doc) {
    setDocs((prev) => prev.map((d) => ({ ...d, opts: { ...d.opts, color: from.opts.color, duplex: from.opts.duplex, copies: from.opts.copies } })));
  }

  const seePrice = () => step("Calculating the price…", "bar", async () => {
    const order = draft.current;
    if (!order || docs.length === 0) return;
    try {
      setQuote(await api.createQuote(order.orderId, order.secret, {
        items: docs.map((d) => ({ document_id: d.documentId, options: { copies: d.opts.copies, color: d.opts.color && colourOk, duplex: d.opts.duplex, page_range: d.opts.pageRange?.trim() || null } })),
      }));
    } catch (e) {
      // this page was opened before the shop switched colour off
      if (code(e) === "color_not_available") setShop((s) => (s ? { ...s, color_available: false } : s));
      throw e;
    }
  });

  const send = () => step("Sending to the shop…", "bar", async () => {
    const order = draft.current;
    if (!order || !quote) return;
    try { await api.submitOrder(order.orderId, order.secret, quote.quote_id); }
    catch (e) {
      if (code(e) === "quote_not_found") setQuote(null);
      // "already submitted" means an earlier tap did reach the shop although its answer never arrived: show that order
      if (code(e) !== "order_not_draft") throw e;
    }
    clearDraft();
    rememberOrder({ id: order.orderId, code: order.shortCode, shopCode, shopName: shop?.name ?? shopCode });
    navigate(`/o/${order.orderId}`);
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
  const busyText = busy ? `${busy}${percent !== null && percent < 100 ? ` ${percent}%` : ""}` : "";
  const one = picked.length === 1 ? picked[0] : null;
  const single = docs.length === 1;
  const bad = firstBad >= 0 ? docs[firstBad] : null;
  const badCheck = firstBad >= 0 ? checks[firstBad] : null;
  return (
    <main className={docs.length ? "with-bar" : ""}>
      <TopBar />
      <header className="shop-head">
        <p className="eyebrow">Print at</p>
        <h1>{shop.name}</h1>
        <span className={`pill ${shop.agent_online ? "ok" : "warn"}`}><i className="dot" />{shop.agent_online ? "Open for prints" : "Shop computer offline"}</span>
      </header>
      {!shop.agent_online && (
        <p className="note" role="status">The shop's printer computer looks offline. You can still send your file; it will wait for the shop.</p>
      )}
      <Steps labels={["File", "Settings", "Send"]} current={docs.length === 0 ? 1 : !quote ? 2 : 3} />

      {docs.length === 0 && (
        <section className="rise">
          <label className={`drop${picked.length ? " has" : ""}${dragging ? " over" : ""}`}
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop} onPointerDown={warmPdfReader}>
            <input type="file" accept="application/pdf,.pdf" multiple aria-label="Choose a PDF to print" disabled={!!busy}
                   onChange={(e) => { const list = [...(e.target.files ?? [])]; e.target.value = ""; choose(list); }} />
            <span className="drop-icon">{picked.length ? <Icon.file size={28} /> : <Icon.upload size={28} />}</span>
            {one ? <><strong className="ellipsis">{one.name}</strong><small>{fileSize(one.size)} · tap to choose another</small></>
              : picked.length ? <><strong>{picked.length} files chosen</strong><small>tap to choose others</small></>
              : <><strong>Choose a PDF</strong><small>Tap to pick one or more files from your phone</small></>}
          </label>
          {(error || unprintable) && <p ref={alertAt} role="alert" className="error">{error ?? PDF_PROBLEM[unprintable!]}</p>}
          {one && !unprintable && <PdfPreview file={one} onProblem={setUnprintable} />}
          {picked.length > 1 && (
            <ul className="picked">
              {picked.map((f, i) => <li key={i}><span className="ellipsis">{f.name}</span><small>{fileSize(f.size)}</small></li>)}
            </ul>
          )}
          {picked.length > 0 && !unprintable && (
            <button className="primary big" onClick={() => upload(picked)} disabled={!!busy}>
              {busy ? <><i className="spinner" />{busyText}</> : <>Continue<Icon.arrow size={20} /></>}
            </button>
          )}
          {percent !== null && <div className="progress" role="progressbar" aria-label="Upload" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{ transform: `scaleX(${progress})` }} /></div>}
          {picked.length === 0 && !error && <p className="hint">No app and no account. You see the price before anything is sent.</p>}
          {picked.length === 0 && <YourOrders shopCode={shopCode} />}
        </section>
      )}

      {docs.length > 0 && (
        <section className="rise">
          {docs.map((d, i) => (
            <DocCard key={d.documentId} doc={d} check={checks[i]} rates={rates} colourOk={colourOk} single={single} open={single || openId === d.documentId}
                     locked={!!busy || !!quote} exactPaise={exact.get(d.documentId)} file={files.current.get(d.documentId)}
                     onOpen={() => setOpenId(d.documentId)} onChange={(next) => change(d.documentId, next)}
                     onRemove={() => remove(d.documentId)} onSameForAll={() => sameForAll(d)} />
          ))}

          {!quote && docs.length < MAX_FILES && (
            <label className={`button add-file${busy ? " off" : ""}`}>
              <input type="file" accept="application/pdf,.pdf" multiple aria-label="Add another PDF" disabled={!!busy}
                     onChange={(e) => { const list = [...(e.target.files ?? [])]; e.target.value = ""; addMore(list); }} />
              {busy && busyAt === "files" ? <><i className="spinner dark" />{busyText}</> : <><Icon.upload size={18} />Add another file</>}
            </label>
          )}
          {percent !== null && <div className="progress" role="progressbar" aria-label="Upload" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{ transform: `scaleX(${progress})` }} /></div>}

          {error && <p ref={alertAt} role="alert" className="error">{error}</p>}

          <div className="bar">
            {!quote ? (
              <>
                <div className="bar-price">
                  {bad && badCheck && !badCheck.ok && (
                    <p role="alert" className="error">
                      {single ? "" : `${bad.fileName}: `}
                      {badCheck.code === "invalid_page_range" ? `Check the page range: this file has ${pagesText(bad.pageCount)}.` : "Copies must be between 1 and 100."}
                    </p>
                  )}
                  {rates && allOk && (
                    <p className="estimate">About <strong key={totals.paise} className="swap">{rupees(totals.paise)}</strong>{" "}
                      <small>{single && checks[0].ok ? `(${checks[0].printedSides} sides × ${rupees(checks[0].paisePerSide)})` : `${docs.length} files · ${totals.sides} sides`}</small>
                    </p>
                  )}
                  {!rates && allOk && <p className="meta">The price is shown in the next step.</p>}
                </div>
                <button className="primary" onClick={seePrice} disabled={!!busy || !allOk}>{busy && busyAt === "bar" ? <><i className="spinner" />{busy}</> : "See exact price"}</button>
              </>
            ) : (
              <div className="quote rise" aria-live="polite">
                <div>
                  <p className="total">{rupees(quote.total_paise)}</p>
                  <p className="meta">{quote.items.length === 1 ? `${quote.items[0].printed_sides} sides × ${rupees(quote.items[0].paise_per_side)}` : `${quote.items.length} files`} · pay at the counter</p>
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

const summary = (o: Options) =>
  `${o.color ? "Colour" : "Black & white"} · ${o.duplex ? "Both sides" : "One side"} · ${Number.isFinite(o.copies) ? o.copies : 1} ${o.copies === 1 ? "copy" : "copies"}${o.pageRange?.trim() ? ` · pages ${o.pageRange.trim()}` : ""}`;

/** One uploaded file: what it is, what it costs, and (when open) how it is to be printed. */
function DocCard({ doc, check, rates, colourOk, single, open, locked, exactPaise, file, onOpen, onChange, onRemove, onSameForAll }: {
  doc: Doc; check: Estimate; rates: Schemas["RateCardPublic"] | null; colourOk: boolean; single: boolean; open: boolean; locked: boolean;
  exactPaise: number | undefined; file: File | undefined;
  onOpen: () => void; onChange: (next: Partial<Pick<Doc, "opts" | "somePages">>) => void; onRemove: () => void; onSameForAll: () => void;
}) {
  const price = exactPaise !== undefined ? rupees(exactPaise) : rates && check.ok ? rupees(check.amountPaise) : null;
  const head = (
    <>
      <span className="file-badge"><Icon.file size={22} /></span>
      <div>
        <strong className="ellipsis">{doc.fileName}</strong>
        <p className="meta"><span>{pagesText(doc.pageCount)}</span>{!open && ` · ${summary(doc.opts)}`}</p>
      </div>
      {!single && price ? <strong className="doc-price">{price}</strong> : single ? <span className="tick"><Icon.check size={16} /></span> : <span />}
    </>
  );
  return (
    <div className={`card doc${open ? " open" : ""}`}>
      {single || open ? <div className="filecard">{head}</div>
        : <button type="button" className="filecard" aria-expanded={false} aria-label={`Print settings for ${doc.fileName}`} onClick={onOpen}>{head}</button>}
      {open && <DocSettings doc={doc} rates={rates} colourOk={colourOk} single={single} locked={locked} file={file} onChange={onChange} onRemove={onRemove} onSameForAll={onSameForAll} />}
    </div>
  );
}

/** The settings of the open file. A component of its own so "Look at the file" closes with the card. */
function DocSettings({ doc, rates, colourOk, single, locked, file, onChange, onRemove, onSameForAll }: {
  doc: Doc; rates: Schemas["RateCardPublic"] | null; colourOk: boolean; single: boolean; locked: boolean; file: File | undefined;
  onChange: (next: Partial<Pick<Doc, "opts" | "somePages">>) => void; onRemove: () => void; onSameForAll: () => void;
}) {
  const [peek, setPeek] = useState(false);
  const opts = doc.opts;
  const set = (change: Partial<Options>) => onChange({ opts: { ...opts, ...change } });
  // what this file would cost with one setting changed, shown under each choice
  const priceWith = (change: Partial<Options>): string | undefined => {
    if (!rates) return undefined;
    const e = estimate(doc.pageCount, { ...opts, ...change }, rates);
    // while the page range or the copies cannot be priced, the line under each choice stays (empty), so nothing jumps under the thumb that is typing
    return e.ok ? rupees(e.amountPaise) : String.fromCharCode(160);   // a no-break space
  };
  const label = `Print settings${single ? "" : ` for ${doc.fileName}`}`;
  return (
    <>
      <fieldset className="doc-options" disabled={locked} aria-label={label}>
        <h2>Print settings</h2>
        {colourOk
          ? <Segmented label="Colour" value={opts.color ? "color" : "bw"} onChange={(v) => set({ color: v === "color" })}
                       options={[{ value: "bw", label: "Black & white", hint: priceWith({ color: false }) }, { value: "color", label: "Colour", hint: priceWith({ color: true }) }]} />
          : <p className="note" role="note">This shop prints in black &amp; white only.</p>}
        <Segmented label="Sides" value={opts.duplex ? "duplex" : "simplex"} onChange={(v) => set({ duplex: v === "duplex" })}
                   options={[{ value: "simplex", label: "One side", hint: priceWith({ duplex: false }) }, { value: "duplex", label: "Both sides", hint: priceWith({ duplex: true }) }]} />
        <Stepper label="Copies" value={opts.copies} min={1} max={100} onChange={(copies) => set({ copies })} />
        <Segmented label="Pages" value={doc.somePages ? "some" : "all"}
                   onChange={(v) => onChange(v === "some" ? { somePages: true } : { somePages: false, opts: { ...opts, pageRange: null } })}
                   options={[{ value: "all", label: "All pages" }, { value: "some", label: "Some pages" }]} />
        {doc.somePages && (
          <label className="field">
            <span className="field-label">Which pages? <small>for example 1-3, 5</small></span>
            <input type="text" inputMode="text" autoFocus value={opts.pageRange ?? ""} placeholder={`1-${doc.pageCount}`}
                   onChange={(e) => set({ pageRange: e.target.value || null })} />
          </label>
        )}
      </fieldset>
      <div className="file-actions">
        {/* rendered only once opened: the preview sizes itself to the space it is given */}
        {file && <details className="peek" onToggle={(e) => setPeek(e.currentTarget.open)}><summary>Look at the file</summary>{peek && <PdfPreview file={file} />}</details>}
        {!single && <button className="link" onClick={onSameForAll} disabled={locked}>Use these settings for all files</button>}
        <button className="link" onClick={onRemove} disabled={locked}>{single ? "Choose another file" : "Remove"}</button>
      </div>
    </>
  );
}
