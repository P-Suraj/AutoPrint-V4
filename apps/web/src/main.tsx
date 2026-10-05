import { StrictMode, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { forgetShop, normalizeShopCode, savedShops } from "./shopCode";
import OrderPage from "./pages/OrderPage";
import ShopPage from "./pages/ShopPage";
import ShopDashboard from "./pages/ShopDashboard";
import "./styles.css";

function Home() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [shops, setShops] = useState(savedShops);
  const [error, setError] = useState<string | null>(null);

  function go(e: FormEvent) {
    e.preventDefault();
    const { code, valid } = normalizeShopCode(text);
    if (!valid) { setError("A shop code is three letters and three numbers, like ABC123. It is on the sign at the counter."); return; }
    navigate(`/s/${code}`);
  }

  return (
    <main>
      <h1>AutoPrint</h1>
      {shops.length > 0 && (
        <section aria-label="Your shops">
          {shops.map((s) => (
            <div key={s.code} style={{ display: "flex", gap: 8 }}>
              <button className="primary" style={{ flex: 1 }} onClick={() => navigate(`/s/${s.code}`)}>Print at {s.name}</button>
              <button className="link" aria-label={`Forget ${s.name}`} onClick={() => { forgetShop(s.code); setShops(savedShops()); }}>Remove</button>
            </div>
          ))}
        </section>
      )}
      <form onSubmit={go}>
        <section>
          <label>
            Shop code
            <small>Scan the QR code at the counter, or type the code shown there.</small>
            <input type="text" className="code" value={text} maxLength={10} autoCapitalize="characters" autoComplete="off" spellCheck={false}
                   placeholder="ABC123" onChange={(e) => { setText(e.target.value); setError(null); }} />
          </label>
          {error && <p role="alert" className="error">{error}</p>}
          <button type="submit" className="primary" disabled={text.trim() === ""}>Continue</button>
        </section>
      </form>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/s/:shopCode" element={<ShopPage />} />
        <Route path="/shop" element={<ShopDashboard />} />
        <Route path="/o/:orderId" element={<OrderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
