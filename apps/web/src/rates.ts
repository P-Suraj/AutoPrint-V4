// The shopkeeper's price form. A price list is stored as "slabs" (see apps/api/app/pricing.py); the form shows each
// kind of print as a base price plus optional bulk prices. These two functions go from one to the other and back.
import type { Schemas } from "./api";

type Slab = Schemas["Slab"];
type RateTable = Schemas["RateTable"];

/** One line of the form: the price per side for a job of at least `from` sides. Text, exactly as typed. */
export type Tier = { from: string; price: string };
export const KINDS = ["bw.simplex", "bw.duplex", "color.simplex", "color.duplex"] as const;
export type Kind = (typeof KINDS)[number];
export type PriceForm = Record<Kind, Tier[]>;
export const KIND_LABEL: Record<Kind, string> = {
  "bw.simplex": "Black & white, one side", "bw.duplex": "Black & white, both sides",
  "color.simplex": "Colour, one side", "color.duplex": "Colour, both sides",
};

const MAX_PAISE = 10_000_000;                       // ₹1,00,000 a side: a typing slip, not a price
const ORDINAL = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"];
const nth = (i: number) => ORDINAL[i] ?? `${i + 1}th`;

/** 200 -> "2", 250 -> "2.50". */
export function paiseToText(paise: number): string {
  const r = Math.floor(paise / 100), p = paise % 100;
  return p === 0 ? String(r) : `${r}.${String(p).padStart(2, "0")}`;
}

/** "2" -> 200, "2.5" -> 250, "₹ 2.50" -> 250. Null when it is not an amount of money (more than two decimals, negative, words). */
export function textToPaise(text: string): number | null {
  const m = /^(\d{1,7})(?:\.(\d{1,2}))?$/.exec(text.replace(/[₹\s,]/g, ""));
  if (!m) return null;
  const paise = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return paise <= MAX_PAISE ? paise : null;
}

export function slabsToTiers(slabs: Slab[]): Tier[] {
  return slabs.map((s) => ({ from: String(s.from_sides), price: paiseToText(s.paise_per_side) }));
}

export const emptyForm = (): PriceForm => ({
  "bw.simplex": [{ from: "1", price: "" }], "bw.duplex": [{ from: "1", price: "" }],
  "color.simplex": [{ from: "1", price: "" }], "color.duplex": [{ from: "1", price: "" }],
});

export function tablesToForm(bw: RateTable, color: RateTable): PriceForm {
  return { "bw.simplex": slabsToTiers(bw.simplex), "bw.duplex": slabsToTiers(bw.duplex),
           "color.simplex": slabsToTiers(color.simplex), "color.duplex": slabsToTiers(color.duplex) };
}

export type Slabs = { ok: true; slabs: Slab[] } | { ok: false; error: string };

/** The first tier always starts at 1 side, whatever its `from` says (the form does not show that box). */
export function tiersToSlabs(tiers: Tier[], label: string): Slabs {
  const bad = (error: string): Slabs => ({ ok: false, error: `${label}: ${error}` });
  if (tiers.length === 0) return bad("enter a price.");
  const rows: { from: number; paise: number }[] = [];
  for (let i = 0; i < tiers.length; i++) {
    const which = tiers.length === 1 ? "the price" : `the ${nth(i)} price`;
    const text = tiers[i].price.trim();
    if (text === "") return bad(i === 0 ? "enter a price." : `enter ${which}, or remove that line.`);
    const paise = textToPaise(text);
    if (paise === null) return bad(`${which} must be an amount in rupees, like 2 or 2.50.`);
    let from = 1;
    if (i > 0) {
      const typed = tiers[i].from.trim();
      if (!/^\d{1,7}$/.test(typed)) return bad(`${which} needs a whole number of sides to start from.`);
      from = Number(typed);
      const before = rows[i - 1].from;
      if (from <= before) return bad(`${which} must start after ${before} ${before === 1 ? "side" : "sides"}.`);
    }
    rows.push({ from, paise });
  }
  return { ok: true, slabs: rows.map((r, i) => ({ from_sides: r.from, to_sides: i === rows.length - 1 ? null : rows[i + 1].from - 1, paise_per_side: r.paise })) };
}

export type Tables = { ok: true; bw: RateTable; color: RateTable } | { ok: false; error: string };

/**
 * The whole form as the two tables the server stores. A shop that does not print in colour does not see the colour
 * prices, so they cannot stop it saving: colour lines it never filled in take the black & white prices.
 */
export function formToTables(form: PriceForm, colorEnabled: boolean): Tables {
  const out = {} as Record<Kind, Slab[]>;
  for (const kind of KINDS) {
    const hidden = !colorEnabled && kind.startsWith("color.");
    const r = tiersToSlabs(form[kind], KIND_LABEL[kind]);
    if (r.ok) out[kind] = r.slabs;
    else if (hidden) out[kind] = out[kind === "color.simplex" ? "bw.simplex" : "bw.duplex"];
    else return { ok: false, error: r.error };
  }
  return { ok: true, bw: { simplex: out["bw.simplex"], duplex: out["bw.duplex"] }, color: { simplex: out["color.simplex"], duplex: out["color.duplex"] } };
}
