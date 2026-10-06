// Price ESTIMATE shown while the customer picks settings. The server's quote is the only authoritative
// price. This mirrors apps/api/app/pricing.py and is tested against contracts/pricing_vectors.json.
import type { Schemas } from "./api";

export type Rates = Pick<Schemas["RateCardPublic"], "bw" | "color">;
export type Options = { copies: number; color: boolean; duplex: boolean; pageRange: string | null };
export type Estimate =
  | { ok: true; selectedPages: number; printedSides: number; paisePerSide: number; amountPaise: number }
  | { ok: false; code: "invalid_page_range" | "invalid_copies" };

const RANGE = /^\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*$/;

/** Returns the selected page numbers, or null when the text is not a valid range for this document. */
export function parsePageRange(text: string | null, pageCount: number): number[] | null {
  if (text === null || text.trim() === "") return Array.from({ length: pageCount }, (_, i) => i + 1);
  const value = text.trim();
  if (!RANGE.test(value)) return null;
  const pages = new Set<number>();
  for (const part of value.split(",")) {
    const [a, b] = part.trim().split("-");
    const start = Number(a);
    const end = b === undefined ? start : Number(b);
    if (start < 1 || end < start || end > pageCount) return null;
    for (let p = start; p <= end; p++) pages.add(p);
  }
  return [...pages].sort((x, y) => x - y);
}

export function estimate(pageCount: number, o: Options, rates: Rates): Estimate {
  if (!Number.isInteger(o.copies) || o.copies < 1 || o.copies > 100) return { ok: false, code: "invalid_copies" };
  const pages = parsePageRange(o.pageRange, pageCount);
  if (pages === null) return { ok: false, code: "invalid_page_range" };
  const sides = pages.length * o.copies;
  const slabs = (o.color ? rates.color : rates.bw)[o.duplex ? "duplex" : "simplex"];
  const slab = slabs.find((s) => s.to_sides === null || s.to_sides === undefined || sides <= s.to_sides);
  const rate = slab ? slab.paise_per_side : 0;
  return { ok: true, selectedPages: pages.length, printedSides: sides, paisePerSide: rate, amountPaise: sides * rate };
}

/** The Indian way of grouping digits: 1234567 -> "12,34,567". Written out so every phone shows the same thing. */
function grouped(n: number): string {
  const s = String(n);
  if (s.length <= 3) return s;
  return `${s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${s.slice(-3)}`;
}

/** Display only: 600 -> "₹6", 650 -> "₹6.50", 30000000 -> "₹3,00,000". Money is always integer paise internally. */
export function rupees(paise: number): string {
  const r = Math.floor(paise / 100);
  const p = paise % 100;
  return p === 0 ? `₹${grouped(r)}` : `₹${grouped(r)}.${String(p).padStart(2, "0")}`;
}
