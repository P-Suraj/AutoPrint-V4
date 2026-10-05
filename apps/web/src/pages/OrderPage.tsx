// Status page. Polls the API; never shows anything the server did not say. Wording comes from the server
// (apps/api/app/wording.py) so it can never claim "printed" before the evidence rule allows it.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Schemas } from "../api";
import { rupees } from "../estimate";
import { loadSecret } from "../store";

const FINAL = new Set(["closed", "cancelled", "expired"]);

export default function OrderPage() {
  const { orderId = "" } = useParams();
  const secret = loadSecret(orderId);
  const [order, setOrder] = useState<Schemas["OrderView"] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [stale, setStale] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const failures = useRef(0);

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

  async function cancel() {
    if (!secret || !window.confirm("Cancel this print request?")) return;
    setCancelling(true);
    try { await api.cancelOrder(orderId, secret); window.clearTimeout(timer.current); await refresh(); }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError("unknown", "Could not cancel.")); }
    finally { setCancelling(false); }
  }

  if (!secret) return <main><h1>Order not available</h1><p>This order can only be opened in the browser where it was started.</p></main>;
  if (error && !order) return <main><h1>Order not available</h1><p role="alert" className="error">{error.message}</p><Link to="/">Start a new order</Link></main>;
  if (!order) return <main><h1>Your order</h1><p>Loading…</p></main>;

  return (
    <main>
      <header><p className="eyebrow">{order.shop_name}</p><h1>Order <span className="code">{order.short_code}</span></h1></header>
      {stale && <p className="note" role="status">Updates are delayed. Retrying…</p>}
      <ul className="jobs">
        {order.jobs.map((j) => (
          <li key={j.job_id}><strong>{j.document_name}</strong><span data-status={j.status}>{j.customer_message}</span></li>
        ))}
      </ul>
      {order.amount_paise != null && <p className="meta">{rupees(order.amount_paise)} · pay at the counter</p>}
      {order.status === "submitted" && order.approval_expires_at && <p className="meta">The shop has until {new Date(order.approval_expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to approve this.</p>}
      {order.can_cancel && <button className="link danger" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel this print"}</button>}
      {error && <p role="alert" className="error">{error.message}</p>}
    </main>
  );
}
