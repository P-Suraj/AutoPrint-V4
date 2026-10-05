import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import OrderPage from "./pages/OrderPage";
import ShopPage from "./pages/ShopPage";
import ShopDashboard from "./pages/ShopDashboard";
import "./styles.css";

function Home() {
  return (
    <main>
      <h1>AutoPrint</h1>
      <p>Scan the QR code at the print shop counter to send a document.</p>
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
