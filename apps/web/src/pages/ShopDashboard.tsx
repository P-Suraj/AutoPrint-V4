// The shopkeeper's page. Today it is reached through a private link (/shop#key=...) handed over by the founder.
// The key is read once from the link fragment (which browsers never send to a server), kept in this browser, and
// removed from the address bar. Later sign-in methods (phone, email) will end by giving this page the same kind of key.
import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import { ApiError, shopApi, shopAuth, type Schemas } from "../api";
import { KINDS, KIND_LABEL, emptyForm, formToTables, tablesToForm, type Kind, type PriceForm, type Tier } from "../rates";
import { Icon, Segmented, TopBar, timeAgo } from "../ui";
import "../shop-settings.css";

const KEY = "ap_shop_key";
// The same limit the server uses when it tells customers a shop is offline (agent_online_seconds, 45 by default):
// the shopkeeper and the customer must not be told different things about the same computer.
const ONLINE_WITHIN_MS = 45_000;
const REFRESH_MS = 10_000;
// The newest installer of the Windows app. The founder publishes each build as a GitHub release with this file name.
const INSTALLER_URL: string = import.meta.env.VITE_INSTALLER_URL ?? "https://github.com/P-Suraj/AutoPrint-V4/releases/latest/download/AutoPrintSetup.exe";

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
      <TopBar />
      <header className="hero">
        <h1>AutoPrint for shops</h1>
        <p>Customers send their files from their phones. You approve, the printer does the rest.</p>
      </header>
      <div className="card rise">
        {state === "checking" ? <p className="center"><i className="spinner dark" />Signing you in…</p> : state === "sent" ? (
          <div className="center">
            <span className="art done small"><Icon.check size={26} /></span>
            <p role="status">If that email is registered for a shop, a sign-in link is on its way. Open it on this phone or computer. It can take a minute.</p>
            <button className="link" onClick={() => setState("idle")}>Use a different email</button>
          </div>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); if (email.includes("@")) void send(); }}>
            <label className="field">
              <span className="field-label">Your email <small>The address AutoPrint has for your shop.</small></span>
              <input type="email" inputMode="email" autoComplete="email" autoCapitalize="none" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
            </label>
            <button type="submit" className="primary big" disabled={state === "sending" || !email.includes("@")}>{state === "sending" ? <><i className="spinner" />Sending…</> : "Email me a sign-in link"}</button>
            <p className="hint">Have a private link from AutoPrint? Just open it; it signs you in by itself.</p>
          </form>
        )}
        {error && <p role="alert" className="error">{error}</p>}
      </div>
    </main>
  );
}

export default function ShopDashboard() {
  const [key, setKey] = useState(readKey);
  // a private link opened in a tab that already shows this page changes only the fragment: no reload happens
  useEffect(() => {
    const onHash = () => { if (/[#&]key=/.test(window.location.hash)) setKey(readKey()); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  if (!key) return <SignIn onKey={setKey} />;
  return <Dashboard shopKey={key} onSignOut={() => { try { localStorage.removeItem(KEY); } catch { /* nothing to do */ } setKey(null); }} />;
}

function Dashboard({ shopKey: key, onSignOut }: { shopKey: string; onSignOut: () => void }) {
  const [me, setMe] = useState<Schemas["ShopMe"] | null>(null);
  const [devices, setDevices] = useState<Schemas["ShopDevice"][] | null>(null);
  const [now, setNow] = useState(Date.now);
  const [code, setCode] = useState("");
  const [found, setFound] = useState<Schemas["ShopPairLookup"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pairError, setPairError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expired, setExpired] = useState(false);
  const [copied, setCopied] = useState(false);
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    let alive = true;
    QRCode.toDataURL(`${window.location.origin}/s/${me.shop_code}`, { width: 400, margin: 1, errorCorrectionLevel: "M" }).then((u) => alive && setQr(u)).catch(() => undefined);
    return () => { alive = false; };
  }, [me]);

  const refresh = useCallback(async () => {
    try {
      const list = (await shopApi.devices(key)).devices;
      // an unchanged list keeps its object, so only the "last seen" times are redrawn
      setDevices((prev) => (prev && JSON.stringify(prev) === JSON.stringify(list) ? prev : list)); setNow(Date.now()); setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "unauthorized") setExpired(true);
      else setError(msg(e));
    }
  }, [key]);

  // Who is signed in. If the first try fails (no network at the counter for a moment) it is tried again with the list.
  const loadMe = useCallback(() => {
    shopApi.me(key).then(setMe).catch((e) => (e instanceof ApiError && e.code === "unauthorized" ? setExpired(true) : setError(msg(e))));
  }, [key]);
  useEffect(() => { loadMe(); }, [loadMe]);

  // The page keeps itself current: the shopkeeper never needs a refresh button to see a computer come online.
  useEffect(() => {
    if (expired) return;
    const tick = () => { if (document.visibilityState !== "visible") return; void refresh(); if (!me) loadMe(); };
    void refresh();
    const t = window.setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);          // back on this tab: show the truth now, not in ten seconds
    return () => { window.clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, [refresh, expired, me, loadMe]);

  // Typing the eighth character is enough: the code is looked up by itself.
  const clean = code.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 8);
  useEffect(() => {
    setFound(null); setPairError(null);
    if (clean.length !== 8) return;
    let alive = true;
    setBusy(true);
    shopApi.lookup(key, clean).then((r) => alive && setFound(r)).catch((e) => alive && setPairError(msg(e))).finally(() => alive && setBusy(false));
    return () => { alive = false; setBusy(false); };
  }, [clean, key]);

  async function connect() {
    setPairError(null); setBusy(true);
    try {
      const r = await shopApi.approve(key, clean);
      setNote(`Connected: ${r.display_name}. The app on that computer will open in a few seconds.`);
      setCode(""); await refresh();
    } catch (e) { setPairError(msg(e)); } finally { setBusy(false); }
  }
  async function disconnect(id: string) {
    if (!window.confirm("Disconnect this computer? It will stop receiving print jobs.")) return;
    try { await shopApi.revoke(key, id); await refresh(); } catch (e) { setError(msg(e)); }
  }

  if (expired) {
    return (
      <main>
        <TopBar />
        <div className="card center rise">
          <h1>Please sign in again</h1>
          <p role="alert">This sign-in is no longer valid. Sign in with your email, or ask AutoPrint for a new link.</p>
          <button className="primary big" onClick={onSignOut}>Sign in</button>
        </div>
      </main>
    );
  }

  const link = me ? `${window.location.origin}/s/${me.shop_code}` : "";
  async function copyLink() {
    try { await navigator.clipboard.writeText(link); setCopied(true); window.setTimeout(() => setCopied(false), 2000); }
    catch { window.prompt("Copy this link:", link); }
  }
  const canShare = typeof navigator.share === "function";

  const active = (devices ?? []).filter((d) => !d.revoked);
  const gone = (devices ?? []).filter((d) => d.revoked);
  const isOnline = (d: Schemas["ShopDevice"]) => !!d.last_seen_at && now - new Date(d.last_seen_at).getTime() < ONLINE_WITHIN_MS;
  const online = active.some(isOnline);
  const shown = code.length > 4 || clean.length > 4 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;


  return (
    <main className="desk">
      <TopBar to="/shop"><button className="link" onClick={onSignOut}>Sign out</button></TopBar>

      <header className="desk-head">
        <div>
          <p className="eyebrow">Shop dashboard</p>
          <h1>{me ? me.shop_name : "AutoPrint for shops"}</h1>
        </div>
        {me && <span className="pill"><span className="muted-label">Shop code</span><span className="code">{me.shop_code}</span></span>}
      </header>

      {devices === null ? <div className="skeleton block" /> : (
        <section className={`status-hero ${online ? "ok" : active.length ? "warn" : "new"} rise`} role="status">
          <span className={`art ${online ? "done" : active.length ? "hold" : "wait"}`}>{online ? <Icon.check size={34} /> : active.length ? <Icon.alert size={30} /> : <Icon.monitor size={30} />}</span>
          <div>
            {online ? <><h2>Your shop is open for prints</h2><p>The shop computer is connected. New print requests appear in the AutoPrint app there, where you approve them.</p></>
              : active.length ? <><h2>Your shop computer is offline</h2><p>Customers can still send files; they wait until the computer is on. Check that it is switched on, online and that AutoPrint is running.</p></>
              : <><h2>Connect your shop computer</h2><p>One step left: link the computer at your counter, and customers can start sending prints.</p></>}
          </div>
          <div className="hero-stat">
            <strong>{active.filter(isOnline).length}<small> / {active.length}</small></strong>
            <span>computers online</span>
          </div>
        </section>
      )}
      {error && <p role="alert" className="error">{error}</p>}

      <div className="desk-grid">
        <div className="desk-main">
          <section className="card rise">
            <div className="card-head">
              <h2><Icon.monitor size={20} />Your computers</h2>
              <span className="meta">Updates by itself every few seconds</span>
            </div>
            {devices !== null && active.length === 0 ? <p className="meta">None connected yet. Use the panel below to connect the first one.</p> : (
              <table className="table">
                <thead><tr><th>Computer</th><th>Status</th><th>Last seen</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {active.map((d) => (
                    <tr key={d.device_id}>
                      <td data-label="Computer"><strong>{d.name}</strong></td>
                      <td data-label="Status"><span className={`pill ${isOnline(d) ? "ok" : ""}`}><i className="dot" />{isOnline(d) ? "Online" : "Offline"}</span></td>
                      <td className="meta" data-label="Last seen">{d.last_seen_at ? timeAgo(d.last_seen_at, now) : "Not seen yet"}</td>
                      <td className="right"><button onClick={() => disconnect(d.device_id)}>Disconnect</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {gone.length > 0 && (
              <details className="peek"><summary>Disconnected computers ({gone.length})</summary>
                <ul className="devices muted">{gone.map((d) => <li key={d.device_id}><i className="dot off" /><div><strong>{d.name}</strong><small>Disconnected</small></div></li>)}</ul>
              </details>
            )}
          </section>

          <section className="card rise">
            <div className="card-head"><h2><Icon.printer size={20} />Connect a computer</h2></div>
            <div className="connect">
              <ol className="howto">
                <li>Install and open the AutoPrint app on the shop computer.
                  <span className="download">
                    <a className="button" href={INSTALLER_URL} rel="noreferrer"><Icon.monitor size={18} />Download AutoPrint for Windows</a>
                    <small className="field-note">Windows may say “Windows protected your PC”. Press More info, then Run anyway.</small>
                  </span>
                </li>
                <li>The app shows a code. Type it here.</li>
                <li>Check the computer's name and confirm.</li>
              </ol>
              <div className="connect-box">
                <input className="code code-input" value={shown} onChange={(e) => { setCode(e.target.value); setNote(null); }} placeholder="ABCD-EFGH" maxLength={9}
                       aria-label="Code shown by the AutoPrint app" autoCapitalize="characters" autoComplete="off" spellCheck={false} />
                {busy && !found && <p className="meta"><i className="spinner dark" />Checking the code…</p>}
                {found && (
                  <div className="confirm rise">
                    <p>Computer name: <strong>{found.display_name}</strong>. Is this the computer at your counter?</p>
                    {found.expired ? <p className="error">This code has expired. Open the app again for a new code.</p>
                      : found.approved ? <p className="error">This code was already used.</p>
                      : <button className="primary big" disabled={busy} onClick={connect}>Yes, connect it to {found.shop_name}</button>}
                  </div>
                )}
                {note && <p role="status" className="found"><span className="tick"><Icon.check size={14} /></span>{note}</p>}
                {pairError && <p role="alert" className="error">{pairError}</p>}
              </div>
            </div>
          </section>

          <ShopSettings shopKey={key} onSaved={(name) => setMe((m) => (m && m.shop_name !== name ? { ...m, shop_name: name } : m))} onExpired={() => setExpired(true)} />
        </div>

        <aside className="desk-side">
          <section className="card rise">
            <div className="card-head"><h2><Icon.qr size={20} />Your customers' link</h2></div>
            <p className="meta">Customers scan the sign at your counter, or open this link. Nothing to install.</p>
            {qr && <img className="qr" src={qr} alt={`QR code for ${link}`} width={200} height={200} />}
            {me && (
              <>
                <p className="linkbox">{link.replace(/^https?:\/\//, "")}</p>
                <div className="actions">
                  <button onClick={copyLink}><Icon.copy size={18} />{copied ? "Copied" : "Copy link"}</button>
                  {canShare && <button onClick={() => { void navigator.share({ title: me.shop_name, text: `Print at ${me.shop_name} from your phone`, url: link }).catch(() => undefined); }}>Share</button>}
                </div>
                <a className="button primary" href={`/poster/${me.shop_code}`} target="_blank" rel="noreferrer"><Icon.printer size={18} />Print your counter sign</a>
              </>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}

// What the shopkeeper decides: the shop's name, whether it prints in colour, and its prices. It loads by itself and
// fails by itself: if this panel cannot load, the rest of the dashboard still works.
function ShopSettings({ shopKey, onSaved, onExpired }: { shopKey: string; onSaved: (name: string) => void; onExpired: () => void }) {
  const [state, setState] = useState<"loading" | "failed" | "ready">("loading");
  const [attempt, setAttempt] = useState(0);
  const [name, setName] = useState("");
  const [colour, setColour] = useState(true);
  const [form, setForm] = useState<PriceForm>(emptyForm);
  const [hasPrices, setHasPrices] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const show = useCallback((s: Schemas["ShopSettings"]) => {
    setName(s.shop_name); setColour(s.color_enabled);
    setHasPrices(!!(s.bw && s.color));
    setForm(s.bw && s.color ? tablesToForm(s.bw, s.color) : emptyForm());
  }, []);

  useEffect(() => {
    let alive = true;
    setState("loading");
    shopApi.settings(shopKey)
      .then((s) => { if (alive) { show(s); setState("ready"); } })
      .catch((e) => { if (!alive) return; if (e instanceof ApiError && e.code === "unauthorized") onExpired(); else setState("failed"); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopKey, attempt, show]);

  const touched = () => { setSaved(false); setError(null); };
  const setTiers = (kind: Kind, tiers: Tier[]) => { touched(); setForm((f) => ({ ...f, [kind]: tiers })); };
  const edit = (kind: Kind, i: number, change: Partial<Tier>) => setTiers(kind, form[kind].map((t, n) => (n === i ? { ...t, ...change } : t)));

  async function save() {
    const shopName = name.trim();
    if (shopName.length < 1 || shopName.length > 80) { setError("Enter your shop's name (up to 80 characters)."); return; }
    const tables = formToTables(form, colour);
    if (!tables.ok) { setError(tables.error); return; }
    setError(null); setSaved(false); setBusy(true);
    try {
      const s = await shopApi.saveSettings(shopKey, { shop_name: shopName, color_enabled: colour, bw: tables.bw, color: tables.color });
      show(s); onSaved(s.shop_name); setSaved(true);
    } catch (e) {
      if (e instanceof ApiError && e.code === "unauthorized") onExpired();
      else setError(e instanceof ApiError && e.code === "invalid_items" ? "These prices could not be saved. Check each price and try again." : msg(e));
    } finally { setBusy(false); }
  }

  return (
    <section className="card rise">
      <div className="card-head">
        <h2><Icon.file size={20} />Prices and shop details</h2>
        {state === "ready" && <span className="meta">Customers see changes as soon as you save</span>}
      </div>
      {state === "loading" ? <div className="skeleton block" /> : state === "failed" ? (
        <>
          <p role="alert" className="error">Could not load your prices. Try again.</p>
          <div><button onClick={() => setAttempt((n) => n + 1)}>Try again</button></div>
        </>
      ) : (
        <form className="settings-form" onSubmit={(e) => { e.preventDefault(); if (!busy) void save(); }} noValidate>
          <div className="settings-top">
            <label className="field">
              <span className="field-label">Shop name <small>What customers see when they open your link.</small></span>
              <input type="text" value={name} maxLength={80} autoComplete="organization" onChange={(e) => { touched(); setName(e.target.value); }} />
            </label>
            <div className="field">
              <Segmented label="Colour printing" value={colour ? "on" : "off"} onChange={(v) => { touched(); setColour(v === "on"); }}
                         options={[{ value: "on", label: "We print in colour" }, { value: "off", label: "Black & white only" }]} />
              <span className="field-note">{colour ? "Customers can choose colour or black & white." : "Customers are told you print in black & white only, and cannot choose colour."}</span>
            </div>
          </div>

          <div className="field">
            <span className="field-label">Prices, in rupees per printed side
              <small>A side is one printed face: a sheet printed on both sides is two sides. A bulk price applies to every side of a job that reaches that many sides.</small>
            </span>
            {!hasPrices && <p className="note">No prices are set yet. Customers cannot order until you save your prices.</p>}
            <div className="price-grid">
              {KINDS.filter((k) => colour || k.startsWith("bw.")).map((kind) => (
                <div key={kind} className="price-group" role="group" aria-label={KIND_LABEL[kind]}>
                  <h3>{KIND_LABEL[kind]}</h3>
                  {form[kind].map((t, i) => (
                    <div key={i} className="tier">
                      {i > 0 && <>
                        <span>From</span>
                        <input className="sides" type="text" inputMode="numeric" maxLength={7} value={t.from} aria-label={`${KIND_LABEL[kind]}: bulk price ${i} starts at this many sides`}
                               onChange={(e) => edit(kind, i, { from: e.target.value })} />
                        <span>sides:</span>
                      </>}
                      <span className="money">
                        <input type="text" inputMode="decimal" maxLength={10} value={t.price} placeholder="0" aria-label={i === 0 ? `${KIND_LABEL[kind]}: price per side` : `${KIND_LABEL[kind]}: bulk price ${i} per side`}
                               onChange={(e) => edit(kind, i, { price: e.target.value })} />
                      </span>
                      <span>per side</span>
                      {i > 0 && <button type="button" className="icon-btn" aria-label={`Remove bulk price ${i} of ${KIND_LABEL[kind]}`} onClick={() => setTiers(kind, form[kind].filter((_, n) => n !== i))}><Icon.x size={16} /></button>}
                    </div>
                  ))}
                  {form[kind].length < 6 && <button type="button" className="link" onClick={() => setTiers(kind, [...form[kind], { from: "", price: "" }])}>Add a bulk price</button>}
                </div>
              ))}
            </div>
          </div>

          <div className="settings-save">
            <button type="submit" className="primary" disabled={busy}>{busy ? <><i className="spinner" />Saving…</> : "Save"}</button>
            <div className="lookup">
              {error ? <p role="alert" className="error">{error}</p> : saved ? <p role="status" className="found"><span className="tick"><Icon.check size={14} /></span>Saved</p> : null}
            </div>
          </div>
        </form>
      )}
    </section>
  );
}
