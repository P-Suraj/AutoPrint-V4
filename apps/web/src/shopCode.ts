// A shop code is three letters then three digits, like TST001. People type it on a phone, so the input is forgiving:
// case, spaces and dashes are ignored, and a character that is clearly the wrong kind for its position is corrected
// (a letter O where a digit belongs becomes 0, a digit 5 where a letter belongs becomes S).
const TO_LETTER: Record<string, string> = { "0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B" };
const TO_DIGIT: Record<string, string> = { O: "0", Q: "0", D: "0", I: "1", L: "1", Z: "2", A: "4", S: "5", G: "6", B: "8" };

export type CodeInput = { code: string; valid: boolean };

export function normalizeShopCode(raw: string): CodeInput {
  const c = raw.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (c.length !== 6) return { code: c, valid: false };
  const fixed = [...c].map((ch, i) => (i < 3 ? (/[0-9]/.test(ch) ? TO_LETTER[ch] ?? ch : ch) : /[A-Z]/.test(ch) ? TO_DIGIT[ch] ?? ch : ch)).join("");
  return { code: fixed, valid: /^[A-Z]{3}[0-9]{3}$/.test(fixed) };
}

// ---- the shops this phone has used, newest first, kept only in this browser
const KEY = "ap.shops";
export type SavedShop = { code: string; name: string };

export function savedShops(): SavedShop[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((s) => typeof s?.code === "string" && typeof s?.name === "string").slice(0, 5) : [];
  } catch { return []; }
}

export function rememberShop(shop: SavedShop): void {
  try {
    const rest = savedShops().filter((s) => s.code !== shop.code);
    localStorage.setItem(KEY, JSON.stringify([shop, ...rest].slice(0, 5)));
  } catch { /* private mode: the home page simply shows no shortcut */ }
}

export function forgetShop(code: string): void {
  try { localStorage.setItem(KEY, JSON.stringify(savedShops().filter((s) => s.code !== code))); } catch { /* nothing to do */ }
}
