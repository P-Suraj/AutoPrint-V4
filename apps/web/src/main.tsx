import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import OrderPage from "./pages/OrderPage";
import ShopPage from "./pages/ShopPage";
import ShopDashboard from "./pages/ShopDashboard";
import PosterPage from "./pages/PosterPage";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/s/:shopCode" element={<ShopPage />} />
        <Route path="/shop" element={<ShopDashboard />} />
        <Route path="/poster/:shopCode" element={<PosterPage />} />
        <Route path="/o/:orderId" element={<OrderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
