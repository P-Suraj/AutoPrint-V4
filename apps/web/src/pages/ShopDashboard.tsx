// The shopkeeper's page. Today it is reached through a private link (/shop#key=...) handed over by the founder.
// The key is read once from the link fragment (which browsers never send to a server), kept in this browser, and
// removed from the address bar. Later sign-in methods (phone, email) will end by giving this page the same kind of key.
import { useCallback, useEffect, useState } from "react";
import { ApiError, shopApi, shopAuth, type Schemas } from "../api";

const KEY = "ap_shop_key";

function readKey(): string | null {
  const m = /[#&]key=([0-9a-f]{64})/.exec(window.location.hash);
  try {
    if (m) {
      localStorage.setItem(KEY, m[1]);
      history.replaceState(null, "", window.location.pathname);
      return m[1];
    }
    return localStorage.getItem(KEY);
  } catch {
    return m ? m[1] : null;
  }
}

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

// Signing in by email: the founder registers the address; the shopkeeper asks for a link, opens it, and comes back here
// with a provider token in the address fragment. The server checks that token and returns an ordinary shop key.
function SignIn({ onKey }: { onKey: (key: string) => void }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "checking">(() => (/[#&]access_token=/.test(window.location.hash) ? "checking" : "idle"));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const m = /[#&]access_token=([^&]+)/.exec(window.location.hash);
    if (!m) return;
    history.replaceState(null, "", window.location.pathname);          // never leave the token in the address bar
    shopAuth.emailFinish(decodeURIComponent(m[1]))
      .then((r) => {
        try { localStorage.setItem(KEY, r.key); } catch { /* private mode: works until the tab closes */ }
        onKey(r.key);
      })
      .catch((e) => { setState("idle"); setError(e instanceof ApiError && e.code === "unauthorized" ? "That email is not registered for a shop, or the link expired. Ask AutoPrint to add your email." : msg(e)); });
  }, [onKey]);

  async function send() {
    setError(null); setState("sending");
    try { await shopAuth.emailStart(email.trim()); setState("sent"); } catch (e) { setError(msg(e)); setState("idle"); }
  }

  return (
    <main>
      <h1>AutoPrint for shops</h1>
      {state === "checking" ? <p>Signing you in…</p> : state === "sent" ? (
        <p role="status">If that email is registered for a shop, a sign-in link is on its way. Open it on this phone or computer. It can take a minute.</p>
      ) : (
        <>
          <p>Sign in with the email address AutoPrint has for your shop, or open the private link you were given.</p>
          <input type="text" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          <button className="primary" disabled={state === "sending" || !email.includes("@")} onClick={send}>Email me a sign-in link</button>
        </>
      )}
      {error && <p role="alert" className="error">{error}</p>}
    </main>
  );
}

export default function ShopDashboard() {
  const [key, setKey] = useState(readKey);
  if (!key) return <SignIn onKey={setKey} />;
  return <Dashboard shopKey={key} onSignOut={() => { try { localStorage.removeItem(KEY); } catch { /* nothing to do */ } setKey(null); }} />;
}

function Dashboard({ shopKey: key, onSignOut }: { shopKey: string; onSignOut: () => void }) {
  const [me, setMe] = useState<Schemas["ShopMe"] | null>(null);
  const [devices, setDevices] = useState<Schemas["ShopDevice"][]>([]);
  const [code, setCode] = useState("");
  const [found, setFound] = useState<Schemas["ShopPairLookup"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!key) return;
    try {
      setMe(await shopApi.me(key));
      setDevices((await shopApi.devices(key)).devices);
    } catch (e) {
      setError(e instanceof ApiError && e.code === "unauthorized" ? "This link is no longer valid. Ask AutoPrint for a new one." : msg(e));
    }
  }, [key]);
  useEffect(() => { void refresh(); }, [refresh]);

  const clean = code.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  async function look() {
    setError(null); setNote(null); setFound(null); setBusy(true);
    try { setFound(await shopApi.lookup(key!, clean)); } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  }
  async function connect() {
    setError(null); setBusy(true);
    try {
      const r = await shopApi.approve(key!, clean);
      setNote(`Connected: ${r.display_name}. The app on that computer will open in a few seconds.`);
      setFound(null); setCode(""); await refresh();
    } catch (e) { setError(msg(e)); } finally { setBusy(false); }
  }
  async function disconnect(id: string) {
    if (!window.confirm("Disconnect this computer? It will stop receiving print jobs.")) return;
    try { await shopApi.revoke(key!, id); await refresh(); } catch (e) { setError(msg(e)); }
  }

  return (
    <main>
      <h1>{me ? me.shop_name : "AutoPrint for shops"}</h1>
      {me && <p><a href={`/poster/${me.shop_code}`} target="_blank" rel="noreferrer">Print your counter sign (QR code)</a></p>}
      <h2>Connect a computer</h2>
      <p>Install the AutoPrint app on the shop computer and open it. Type the code it shows here.</p>
      <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="ABCD-EFGH" maxLength={9} autoCapitalize="characters"
             style={{ fontSize: 24, letterSpacing: 3, textTransform: "uppercase", width: "100%", boxSizing: "border-box" }} />
      {clean.length === 8 && !found && <button disabled={busy} onClick={look}>Check code</button>}
      {found && (
        <div>
          <p>Computer name: <strong>{found.display_name}</strong>. Is this the computer at your counter?</p>
          {found.expired ? <p>This code has expired. Open the app again for a new code.</p>
            : found.approved ? <p>This code was already used.</p>
            : <button disabled={busy} onClick={connect}>Yes, connect it to {found.shop_name}</button>}
        </div>
      )}
      {note && <p role="status">{note}</p>}
      {error && <p role="alert">{error}</p>}

      <p><button className="link" onClick={onSignOut}>Sign out on this browser</button></p>
      <h2>Your computers</h2>
      {devices.length === 0 ? <p>None connected yet.</p> : (
        <ul>
          {devices.map((d) => (
            <li key={d.device_id}>
              {d.name} {d.revoked ? "(disconnected)" : d.last_seen_at ? `· last seen ${new Date(d.last_seen_at).toLocaleString()}` : "· not seen yet"}
              {!d.revoked && <button onClick={() => disconnect(d.device_id)}>Disconnect</button>}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
