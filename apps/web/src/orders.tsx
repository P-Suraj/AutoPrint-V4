// "Your order K7QD": the way back to an order after the tab was closed or the phone was locked.
// Shows only orders sent from this phone that the server still knows; each one is checked with the server, and an
// order the server no longer has is dropped from the phone. Nothing is shown that the server did not say.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type Schemas } from "./api";
import { forgetOrder, loadSecret, savedOrders, type SavedOrder } from "./store";
import { Icon } from "./ui";

const FINAL = new Set(["closed", "cancelled", "expired"]);
type Seen = Schemas["OrderView"] | "unreachable";

function line(seen: Seen | undefined): string {
  if (seen === undefined) return "Checking…";
  if (seen === "unreachable") return "Could not check the status just now. Tap to open.";
  return seen.jobs[0]?.customer_message ?? "Tap to open.";
}

export function YourOrders({ shopCode }: { shopCode?: string }) {
  const [orders, setOrders] = useState<SavedOrder[]>(() => savedOrders().filter((o) => !shopCode || o.shopCode === shopCode));
  const [seen, setSeen] = useState<Record<string, Seen>>({});

  useEffect(() => {
    let alive = true;
    const check = () => {
      for (const o of savedOrders().filter((x) => !shopCode || x.shopCode === shopCode)) {
        const secret = loadSecret(o.id);
        if (!secret) continue;
        api.getOrder(o.id, secret)
          .then((view) => alive && setSeen((s) => ({ ...s, [o.id]: view })))
          .catch((e) => {
            if (!alive) return;
            if (e instanceof ApiError && e.code === "order_not_found") { forgetOrder(o.id); setOrders((list) => list.filter((x) => x.id !== o.id)); }
            else setSeen((s) => (s[o.id] ? s : { ...s, [o.id]: "unreachable" }));      // keep the last real answer if there was one
          });
      }
    };
    check();
    // coming back to the tab (phone unlocked) is exactly when the answer may have changed
    const onShow = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { alive = false; document.removeEventListener("visibilitychange", onShow); };
  }, [shopCode]);

  if (orders.length === 0) return null;
  return (
    <section aria-label="Your orders" className="rise">
      <p className="eyebrow">{orders.length === 1 ? "Your order" : "Your orders"}</p>
      {orders.map((o) => {
        const s = seen[o.id];
        const done = typeof s === "object" && FINAL.has(s.status);
        return (
          <div key={o.id} className="order-row">
            <Link className={`button shop-go order-go${done ? " quiet" : ""}`} to={`/o/${o.id}`}>
              <span className="order-code code">{o.code}</span>
              <span><strong>{line(s)}</strong>{!shopCode && <small>{o.shopName}</small>}</span>
              <Icon.arrow size={20} />
            </Link>
            {done && <button className="icon-btn" aria-label={`Remove order ${o.code} from this phone`} onClick={() => { forgetOrder(o.id); setOrders((list) => list.filter((x) => x.id !== o.id)); }}><Icon.x size={18} /></button>}
          </div>
        );
      })}
    </section>
  );
}
