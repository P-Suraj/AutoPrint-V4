// The front door for a customer who did not scan the counter QR: type the shop code, or tap a shop used before.
// The code is checked while it is typed, so the customer sees the shop's name before going anywhere.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { YourOrders } from "../orders";
import { forgetShop, normalizeShopCode, savedShops } from "../shopCode";
import { Icon, TopBar } from "../ui";

// "none": the server says no shop has this code. "unreachable": the server could not be asked, which is not the same thing.
type Found = { code: string; name: string } | { code: string; name: null; why: "none" | "unreachable" };

export default function HomePage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [shops, setShops] = useState(savedShops);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<Found | null>(null);
  const { code, valid } = normalizeShopCode(text);

  useEffect(() => {
    if (!valid) { setFound(null); return; }
    let alive = true;
    const t = window.setTimeout(() => {
      api.getShop(code).then((s) => alive && setFound({ code, name: s.name }))
        .catch((e) => alive && setFound({ code, name: null, why: e instanceof ApiError && e.code === "shop_not_found" ? "none" : "unreachable" }));
    }, 150);
    return () => { alive = false; window.clearTimeout(t); };
  }, [code, valid]);

  function go(e: FormEvent) {
    e.preventDefault();
    if (!valid) { setError("A shop code is three letters and three numbers, like ABC123. It is on the sign at the counter."); return; }
    navigate(`/s/${code}`);
  }

  const match = found && found.code === code ? found : null;
  return (
    <main>
      <TopBar />
      <header className="hero">
        <h1>Print from your phone</h1>
        <p>Send a PDF to the shop, see the price, and collect your pages at the counter. No app, no account.</p>
      </header>

      <YourOrders />

      {shops.length > 0 && (
        <section aria-label="Your shops" className="rise">
          <p className="eyebrow">Your shops</p>
          {shops.map((s) => (
            <div key={s.code} className="shop-row">
              <button className="shop-go" onClick={() => navigate(`/s/${s.code}`)}>
                <span className="file-badge"><Icon.printer size={20} /></span>
                <span><strong>Print at {s.name}</strong><small className="code">{s.code}</small></span>
                <Icon.arrow size={20} />
              </button>
              <button className="icon-btn" aria-label={`Forget ${s.name}`} onClick={() => { forgetShop(s.code); setShops(savedShops()); }}><Icon.x size={18} /></button>
            </div>
          ))}
        </section>
      )}

      <form onSubmit={go} className="card rise">
        <label className="field">
          <span className="field-label">{shops.length > 0 ? "Another shop" : "Shop code"} <small>Scan the QR code at the counter, or type the code shown there.</small></span>
          <input type="text" inputMode="text" enterKeyHint="go" className="code code-input" value={text} maxLength={10} autoCapitalize="characters" autoComplete="off" spellCheck={false}
                 placeholder="ABC123" onChange={(e) => { setText(e.target.value); setError(null); }} />
        </label>
        {/* one line is always kept for the answer, so the button below never jumps when it arrives */}
        <div className="lookup" role="status">
          {match?.name && <p className="found"><span className="tick"><Icon.check size={14} /></span>{match.name}</p>}
          {match && match.name === null && match.why === "none" && <p className="error">No shop has the code {code}. Check the sign at the counter.</p>}
          {match && match.name === null && match.why === "unreachable" && <p className="meta">Could not check the code just now. Check your connection.</p>}
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" className="primary big" disabled={text.trim() === ""}>{match?.name ? <>Print at {match.name}<Icon.arrow size={20} /></> : "Continue"}</button>
      </form>

      <p className="foot">Run a print shop? <Link to="/shop">Open the shop dashboard</Link></p>
    </main>
  );
}
