// Status page. Polls the API; never shows anything the server did not say. Wording comes from the server
// (apps/api/app/wording.py) so it can never claim "printed" before the evidence rule allows it.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Schemas } from "../api";
import { rupees } from "../estimate";
import { loadSecret } from "../store";
import { Icon, TopBar } from "../ui";

const FINAL = new Set(["closed", "cancelled", "expired"]);

type JobStatus = Schemas["OrderJobView"]["status"];
// How many steps of the happy path are behind a job. Other states (declined, cancelled, a problem) have no place on the track.
const STEPS_DONE: Partial<Record<JobStatus, number>> = { awaiting_approval: 1, approved: 2, printing: 2, completed: 4 };
const TRACK = ["Sent", "Approved", "Printer", "Collect"];
const TONE: Record<JobStatus, "wait" | "go" | "done" | "bad" | "off"> = {
  awaiting_approval: "wait", approved: "go", printing: "go", completed: "done",
  failed: "bad", needs_attention: "bad", rejected: "off", cancelled: "off", expired: "off",
};

function StatusArt({ status }: { status: JobStatus }) {
  const tone = TONE[status];
  return (
    <span className={`art ${tone}${status === "printing" ? " printing" : ""}`} aria-hidden="true">
      {status === "completed" ? <Icon.check size={34} />
        : status === "awaiting_approval" ? <Icon.clock size={32} />
        : status === "approved" || status === "printing" ? <><Icon.printer size={32} /><i className="sheet" /></>
        : tone === "bad" ? <Icon.alert size={32} /> : <Icon.x size={30} />}
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

export default function OrderPage() {
  const { orderId = "" } = useParams();
  const secret = loadSecret(orderId);
  const [order, setOrder] = useState<Schemas["OrderView"] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [stale, setStale] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const failures = useRef(0);
  const wasDone = useRef(false);

  const refresh = useCallback(async () => {
    if (!secret) return;
    try {
      const o = await api.getOrder(orderId, secret);
      failures.current = 0; setStale(false); setError(null); setOrder(o);
      if (!FINAL.has(o.status)) timer.current = window.setTimeout(refresh, 4000);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError("unknown", "Something went wrong.");
      if (err.code === "network" || err.status >= 500) {          // transient: keep the last good view, say it is stale, retry slowly
        failures.current += 1; setStale(true);
        timer.current = window.setTimeout(refresh, Math.min(30000, 4000 * 2 ** failures.current));
      } else setError(err);
    }
  }, [orderId, secret]);

  useEffect(() => { refresh(); return () => window.clearTimeout(timer.current); }, [refresh]);

  // A phone in a pocket: buzz once when everything is ready to collect, and say so in the tab title.
  const allDone = !!order && order.jobs.length > 0 && order.jobs.every((j) => j.status === "completed");
  useEffect(() => {
    if (order) document.title = `${allDone ? "Ready to collect" : "Order"} ${order.short_code} · AutoPrint`;
    if (allDone && !wasDone.current) { try { navigator.vibrate?.(200); } catch { /* not supported: nothing to do */ } }
    wasDone.current = allDone;
    return () => { document.title = "AutoPrint"; };
  }, [order, allDone]);

  async function cancel() {
    if (!secret || !window.confirm("Cancel this print request?")) return;
    setCancelling(true);
    try { await api.cancelOrder(orderId, secret); window.clearTimeout(timer.current); await refresh(); }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError("unknown", "Could not cancel.")); }
    finally { setCancelling(false); }
  }

  if (!secret) return <main><TopBar /><div className="card center"><h1>Order not available</h1><p>This order can only be opened in the browser where it was started.</p><Link className="button" to="/">Start a new order</Link></div></main>;
  if (error && !order) return <main><TopBar /><div className="card center"><h1>Order not available</h1><p role="alert" className="error">{error.message}</p><Link className="button" to="/">Start a new order</Link></div></main>;
  if (!order) return <main aria-busy="true"><TopBar /><div className="skeleton title" /><div className="skeleton block" /><p className="sr-only">Loading…</p></main>;

  const live = !FINAL.has(order.status);
  return (
    <main>
      <TopBar />
      <header className={`ticket${allDone ? " done" : ""}`}>
        <p className="eyebrow">{order.shop_name}</p>
        <h1>Order <span className="code">{order.short_code}</span></h1>
        <p className="ticket-hint">Say this code at the counter</p>
      </header>
      {stale && <p className="note" role="status">Updates are delayed. Retrying…</p>}
      {order.jobs.length === 0 && <p className="note">This order has not been sent to the shop yet.</p>}
      <ul className="jobs">
        {order.jobs.map((j) => (
          <li key={j.job_id} className={`card job ${TONE[j.status]}`}>
            <StatusArt status={j.status} />
            <span className="status" data-status={j.status} aria-live="polite">{j.customer_message}</span>
            <strong className="ellipsis doc">{j.document_name}</strong>
            <Track status={j.status} />
          </li>
        ))}
      </ul>
      <div className="order-foot">
        {order.amount_paise != null && <p className="pay"><strong>{rupees(order.amount_paise)}</strong> · pay at the counter</p>}
        {order.status === "submitted" && order.approval_expires_at && <p className="meta">The shop has until {new Date(order.approval_expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to approve this.</p>}
        {live && <p className="meta live"><i className="dot" />This page updates by itself. You can keep it open.</p>}
        {order.can_cancel && <button className="link danger" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel this print"}</button>}
        {!live && <Link className="button" to="/">Print another file</Link>}
        {error && <p role="alert" className="error">{error.message}</p>}
      </div>
    </main>
  );
}
