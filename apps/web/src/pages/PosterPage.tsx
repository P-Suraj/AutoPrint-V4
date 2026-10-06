// A printable A4 counter sign for a shop: big QR code, the shop code to type, and three plain steps.
// Public on purpose: a shop code and its customer link are already printed on the counter.
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import QRCode from "qrcode";
import { ApiError, api, type Schemas } from "../api";
import { normalizeShopCode } from "../shopCode";

export default function PosterPage() {
  const { shopCode = "" } = useParams();
  const { code, valid } = normalizeShopCode(shopCode);
  const [shop, setShop] = useState<Schemas["ShopPublic"] | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const link = `${window.location.origin}/s/${code}`;

  useEffect(() => {
    if (!valid) { setError("That is not a shop code."); return; }
    let alive = true;
    api.getShop(code).then((s) => alive && setShop(s)).catch((e) => alive && setError(e instanceof ApiError ? e.message : "Could not load the shop."));
    QRCode.toDataURL(link, { width: 640, margin: 1, errorCorrectionLevel: "M" }).then((u) => alive && setQr(u));
    return () => { alive = false; };
  }, [code, valid, link]);

  if (error) return <main><h1>AutoPrint</h1><p role="alert" className="error">{error}</p></main>;
  if (!shop || !qr) return <main><p>Loading…</p></main>;

  return (
    <div className="poster">
      <p className="poster-hint no-print">Press <strong>Print</strong> (Ctrl+P) and choose A4. <button onClick={() => window.print()}>Print this sign</button></p>
      <h1>{shop.name}</h1>
      <p className="poster-lead">Print your documents here from your phone</p>
      <img src={qr} alt={`QR code for ${link}`} width={360} height={360} />
      <p className="poster-scan">Scan to start</p>
      <ol>
        <li>Scan the code, or open <strong>{window.location.host}</strong> and type the shop code.</li>
        <li>Choose your PDF and how you want it printed. You see the price first.</li>
        <li>Wait for the shopkeeper to approve. Collect your pages at the counter.</li>
      </ol>
      <p className="poster-code">Shop code: <span className="code">{code}</span></p>
    </div>
  );
}
