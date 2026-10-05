import { describe, expect, it } from "vitest";
import vectors from "../../../contracts/pricing_vectors.json";
import { estimate, parsePageRange, rupees, type Rates } from "./estimate";

const rates = vectors.rules as unknown as Rates;

describe("estimate matches the Python pricing module (shared vectors)", () => {
  for (const c of vectors.cases) {
    const name = `${c.page_count}p x${c.copies} color=${c.color} duplex=${c.duplex} range=${JSON.stringify(c.page_range)}`;
    it(name, () => {
      const got = estimate(c.page_count, { copies: c.copies, color: c.color, duplex: c.duplex, pageRange: c.page_range }, rates);
      const want = c.expect as Record<string, unknown>;
      if ("error" in want) {
        expect(got.ok).toBe(false);
        if (!got.ok) expect(got.code).toBe(want.error);
      } else {
        expect(got).toEqual({
          ok: true,
          selectedPages: want.selected_pages,
          printedSides: want.printed_sides,
          paisePerSide: want.paise_per_side,
          amountPaise: want.amount_paise,
        });
      }
    });
  }
});

describe("details", () => {
  it("three pages at 2 rupees is 6 rupees", () => {
    const got = estimate(3, { copies: 1, color: false, duplex: false, pageRange: null }, rates);
    expect(got.ok && rupees(got.amountPaise)).toBe("₹6");
  });
  it("page ranges are unique and sorted", () => {
    expect(parsePageRange("5, 1-3, 2", 10)).toEqual([1, 2, 3, 5]);
  });
  it("formats rupees", () => {
    expect([rupees(0), rupees(5), rupees(650), rupees(1200)]).toEqual(["₹0", "₹0.05", "₹6.50", "₹12"]);
  });
});
