import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import OrderPage from "./pages/OrderPage";
import ShopPage from "./pages/ShopPage";
import "./styles.css";

// A customer never needs the shopkeeper's pages (or the QR code library they use), so they are not part of the
// first download: they load when someone opens /shop or a poster.
const ShopDashboard = lazy(() => import("./pages/ShopDashboard"));
const PosterPage = lazy(() => import("./pages/PosterPage"));
const waiting = <main aria-busy="true"><div className="skeleton head-shape" /><div className="skeleton drop-shape" /><p className="sr-only">Loading…</p></main>;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/s/:shopCode" element={<ShopPage />} />
        <Route path="/shop" element={<Suspense fallback={waiting}><ShopDashboard /></Suspense>} />
        <Route path="/poster/:shopCode" element={<Suspense fallback={waiting}><PosterPage /></Suspense>} />
        <Route path="/o/:orderId" element={<OrderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
