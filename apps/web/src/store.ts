// The order secret is the customer's only credential. It lives in this browser only, so reopening the
// order link on another phone shows "not available" rather than someone else's order.
const key = (orderId: string) => `ap.order.${orderId}`;

export function saveSecret(orderId: string, secret: string): void {
  try { localStorage.setItem(key(orderId), secret); } catch { /* private mode: the order page will say so */ }
}

export function loadSecret(orderId: string): string | null {
  try { return localStorage.getItem(key(orderId)); } catch { return null; }
}

export function forgetSecret(orderId: string): void {
  try { localStorage.removeItem(key(orderId)); } catch { /* nothing to do */ }
}

// ---- the way back to an order: the orders this phone has SENT and can still open, newest first.
// Not a history: an entry is dropped as soon as the server says the order is gone, and only a handful are kept.
const ORDERS = "ap.orders";
const MAX_ORDERS = 5;
export type SavedOrder = { id: string; code: string; shopCode: string; shopName: string };

const isOrder = (o: unknown): o is SavedOrder => {
  const v = o as Partial<SavedOrder> | null;
  return !!v && typeof v.id === "string" && typeof v.code === "string" && typeof v.shopCode === "string" && typeof v.shopName === "string";
};

/** Only orders whose secret is still on this phone: without it the order cannot be opened anyway. */
export function savedOrders(): SavedOrder[] {
  try {
    const v = JSON.parse(localStorage.getItem(ORDERS) ?? "[]");
    return Array.isArray(v) ? v.filter(isOrder).filter((o) => loadSecret(o.id) !== null).slice(0, MAX_ORDERS) : [];
  } catch { return []; }
}

export function rememberOrder(order: SavedOrder): void {
  try {
    const all = [order, ...savedOrders().filter((o) => o.id !== order.id)];
    for (const old of all.slice(MAX_ORDERS)) forgetSecret(old.id);
    localStorage.setItem(ORDERS, JSON.stringify(all.slice(0, MAX_ORDERS)));
  } catch { /* private mode: the status page still works until the tab closes */ }
}

/** The server said the order is gone (or the customer dismissed a finished one): drop it and its secret. */
export function forgetOrder(orderId: string): void {
  try { localStorage.setItem(ORDERS, JSON.stringify(savedOrders().filter((o) => o.id !== orderId))); } catch { /* nothing to do */ }
  forgetSecret(orderId);
}

// ---- the file being prepared in this tab. Kept for the tab only, so a refresh or the back button during
// "Settings" returns to the uploaded file instead of asking for it again. The secret stays in saveSecret.
const DRAFT = "ap.draft";
export type Draft = {
  shopCode: string; orderId: string; shortCode: string; documentId: string | null; pageCount: number; fileName: string;
  copies: number; color: boolean; duplex: boolean; pageRange: string | null;
};

export function saveDraft(d: Draft): void {
  try { sessionStorage.setItem(DRAFT, JSON.stringify(d)); } catch { /* a refresh will ask for the file again */ }
}

export function loadDraft(shopCode: string): Draft | null {
  try {
    const d = JSON.parse(sessionStorage.getItem(DRAFT) ?? "null") as Draft | null;
    if (!d || d.shopCode !== shopCode || typeof d.orderId !== "string" || typeof d.shortCode !== "string") return null;
    return loadSecret(d.orderId) === null ? null : d;
  } catch { return null; }
}

export function clearDraft(): void {
  try { sessionStorage.removeItem(DRAFT); } catch { /* nothing to do */ }
}
