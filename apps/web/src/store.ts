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
