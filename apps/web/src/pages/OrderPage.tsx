// Status page. Polls the API; never shows anything the server did not say. Wording comes from the server
// (apps/api/app/wording.py) so it can never claim "printed" before the evidence rule allows it.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Schemas } from "../api";
import { rupees } from "../estimate";
import { forgetOrder, loadSecret } from "../store";
import { Icon, TopBar } from "../ui";

const FINAL = new Set(["closed", "cancelled", "expired"]);
// How often the server is asked. Quick while something is about to happen; slower once the customer has been
// waiting for the shop for a while (an approval can take many minutes and each question costs a server call).
// Quickest between the shop's approval and the result: that part lasts a few seconds, so it is a handful of extra
// questions per order, and it is when the customer is standing at the counter watching the page.
export const POLL_MS = 4000;
export const POLL_FAST_MS = 2000;
export const POLL_SLOW_MS = 8000;
export const POLL_SLOW_AFTER_MS = 120_000;
export const RETRY_MAX_MS = 30_000;

type Order = Schemas["OrderView"];
type JobStatus = Schemas["OrderJobView"]["status"];
// How many steps of the happy path are behind a job. Other states (declined, cancelled, a problem) have no place on the track.
const STEPS_DONE: Partial<Record<JobStatus, number>> = { awaiting_approval: 1, approved: 2, printing: 2, completed: 4 };
const TRACK = ["Sent", "Approved", "Printer", "Collect"];
// "hold" is a print the shop is looking at (nothing has gone wrong yet): amber. "bad" is one that could not be made: red.
// The mark and the words of a card always share the one colour of its tone.
const TONE: Record<JobStatus, "wait" | "go" | "done" | "hold" | "bad" | "off"> = {
  awaiting_approval: "wait", approved: "go", printing: "go", completed: "done",
  failed: "bad", needs_attention: "hold", rejected: "off", cancelled: "off", expired: "off",
};

function StatusArt({ status }: { status: JobStatus }) {
  const tone = TONE[status];
  return (
    <span className={`art ${tone}${status === "printing" ? " printing" : ""}`} aria-hidden="true">
      {status === "completed" ? <Icon.check size={34} />
        : status === "awaiting_approval" ? <Icon.clock size={32} />
        : status === "approved" || status === "printing" ? <><Icon.printer size={32} /><i className="sheet" /></>
        : tone === "bad" || tone === "hold" ? <Icon.alert size={32} /> : <Icon.x size={30} />}
    </span>
  );
}

function Track({ status }: { status: JobStatus }) {
  const done = STEPS_DONE[status];
  if (!done) return null;
  return (
    <ol className="track" aria-hidden="true">
      {TRACK.map((label, i) => {
        const n = i + 1;
        const state = n <= done ? "done" : n === done + 1 ? "now" : "todo";
        return <li key={label} className={state}><i>{state === "done" ? <Icon.check size={12} /> : null}</i><span>{label}</span></li>;
      })}
    </ol>
  );
}

// One job card. Redrawn only when its own status or wording changes, not on every poll.
const Job = memo(function Job({ status, message, name }: { status: JobStatus; message: string; name: string }) {
  return (
    <li className={`card job ${TONE[status]}`}>
      <StatusArt status={status} />
      {/* keyed by status: a change of state fades in softly instead of snapping */}
      <span key={status} className="status swap" data-status={status} aria-live="polite">{message}</span>
      <strong className="ellipsis doc">{name}</strong>
      <Track status={status} />
    </li>
  );
});

/** The same answer as last time keeps the same object, so React has nothing to redraw. */
const same = (a: Order | null, b: Order) => a !== null && JSON.stringify(a) === JSON.stringify(b);

export default function OrderPage() {
  const { orderId = "" } = useParams();
  const secret = useMemo(() => loadSecret(orderId), [orderId]);      // read once: the page may itself drop it when the order is gone
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<ApiError | null>(null);          // the order cannot be shown (any more)
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const failures = useRef(0);
  const run = useRef(0);                 // only the newest request may touch the page or plan the next one
  const finished = useRef(false);        // a final state, or an answer that will not change: stop asking
  const started = useRef(Date.now());
  const wasDone = useRef(false);

  const refresh = useCallback(async () => {
    if (!secret) return;
    window.clearTimeout(timer.current);
    const mine = ++run.current;
    // A hidden tab (locked phone, another app) is not asked on behalf of: `onWake` below asks the moment it is seen again.
    const next = (ms: number) => { timer.current = window.setTimeout(() => { if (document.visibilityState !== "hidden") void refresh(); }, ms); };
    try {
      const o = await api.getOrder(orderId, secret);
      if (mine !== run.current) return;
      failures.current = 0; setStale(false); setError(null);
      setOrder((prev) => (same(prev, o) ? prev : o));
      finished.current = FINAL.has(o.status);
      if (!finished.current) {
        const waitingForShop = o.jobs.every((j) => j.status === "awaiting_approval");
        const atThePrinter = o.jobs.some((j) => j.status === "approved" || j.status === "printing");
        next(atThePrinter ? POLL_FAST_MS : waitingForShop && Date.now() - started.current > POLL_SLOW_AFTER_MS ? POLL_SLOW_MS : POLL_MS);
      }
    } catch (e) {
      if (mine !== run.current) return;
      const err = e instanceof ApiError ? e : new ApiError("unknown", "Something went wrong.");
      const passing = err.code === "network" || err.status === 0 || err.status >= 500 || err.status === 429 || err.status === 408;
      if (!passing) {                                              // a definite answer: nothing more to ask
        finished.current = true; setOrder(null); setError(err);
        if (err.code === "order_not_found") forgetOrder(orderId);  // the server no longer has it, so there is nothing to go back to
      } else {                                                     // keep the last good view, say it is delayed, retry more slowly
        failures.current += 1; setStale(true);
        next(Math.min(RETRY_MAX_MS, POLL_MS * 2 ** failures.current));
      }
    }
  }, [orderId, secret]);

  useEffect(() => {
    void refresh();
    // The phone was unlocked, or the network came back: ask now instead of waiting for the next turn.
    const onWake = () => { if (document.visibilityState !== "hidden" && !finished.current) void refresh(); };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);
    return () => {
      run.current += 1; window.clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onWake); window.removeEventListener("online", onWake);
    };
  }, [refresh]);

  // A phone in a pocket: buzz once when everything is ready to collect, and say so in the tab title.
  const allDone = !!order && order.jobs.length > 0 && order.jobs.every((j) => j.status === "completed");
  useEffect(() => {
    if (order) document.title = `${allDone ? "Ready to collect" : "Order"} ${order.short_code} · AutoPrint`;
    if (allDone && !wasDone.current) { try { navigator.vibrate?.(200); } catch { /* not supported: nothing to do */ } }
    wasDone.current = allDone;
    return () => { document.title = "AutoPrint"; };
  }, [order, allDone]);

  async function cancel() {
    if (!secret || cancelling || !window.confirm("Cancel this print request?")) return;
    setCancelling(true); setCancelError(null);
    try { await api.cancelOrder(orderId, secret); }
    catch (e) { setCancelError(e instanceof ApiError ? e.message : "Could not cancel. Please try again."); }
    finally { setCancelling(false); }
    await refresh();                                               // either way, show what the server says now
  }

  if (!secret) return <main><TopBar /><div className="card center"><h1>Order not available</h1><p>This order can only be opened in the browser where it was started.</p><Link className="button" to="/">Start a new order</Link></div></main>;
  if (error) return <main><TopBar /><div className="card center"><h1>Order not available</h1><p role="alert" className="error">{error.message}</p><Link className="button" to="/">Start a new order</Link></div></main>;
  if (!order) {
    return (
      <main aria-busy={!stale}>
        <TopBar />
        {stale ? <p className="note" role="alert">Could not reach AutoPrint. Check your connection; this page keeps trying by itself.</p> : <p className="sr-only">Loading…</p>}
        <div className="skeleton ticket-shape" /><div className="skeleton job-shape" />
      </main>
    );
  }

  const live = !FINAL.has(order.status);
  // Declined, cancelled or run out of time: there is nothing to collect, so no code to say and nothing to pay.
  // A print the shop could not make keeps its code (the customer is sent to the counter) but asks for no money.
  const calledOff = order.jobs.length > 0 && order.jobs.every((j) => TONE[j.status] === "off");
  const nothingToPay = calledOff || (order.jobs.length > 0 && order.jobs.every((j) => TONE[j.status] === "off" || j.status === "failed"));
  return (
    <main>
      <TopBar />
      <header className={`ticket${allDone ? " done" : ""}`}>
        <p className="eyebrow">{order.shop_name}</p>
        <h1>Order <span className="code">{order.short_code}</span></h1>
        {!calledOff && <p className="ticket-hint">Say this code at the counter</p>}
      </header>
      {stale && <p className="note" role="status">Updates are delayed. Check your connection; this page keeps trying by itself.</p>}
      {order.jobs.length === 0 && <p className="note">This order has not been sent to the shop yet.</p>}
      <ul className="jobs">
        {order.jobs.map((j) => <Job key={j.job_id} status={j.status} message={j.customer_message} name={j.document_name} />)}
      </ul>
      <div className="order-foot">
        {order.amount_paise != null && !nothingToPay && <p className="pay"><strong>{rupees(order.amount_paise)}</strong> · pay at the counter</p>}
        {order.status === "submitted" && order.approval_expires_at && order.jobs.some((j) => j.status === "awaiting_approval") && <p className="meta">The shop has until {new Date(order.approval_expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to approve this.</p>}
        {live && <p className="meta live"><i className="dot" />This page updates by itself. You can keep it open.</p>}
        {order.can_cancel && <button className="link danger" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel this print"}</button>}
        {cancelError && <p role="alert" className="error">{cancelError}</p>}
        {!live && <Link className="button" to="/">Print another file</Link>}
      </div>
    </main>
  );
}
