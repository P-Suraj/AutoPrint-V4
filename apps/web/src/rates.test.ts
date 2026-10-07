import { describe, expect, it } from "vitest";
import { emptyForm, formToTables, paiseToText, slabsToTiers, tablesToForm, textToPaise, tiersToSlabs } from "./rates";

const flat = (paise: number) => [{ from_sides: 1, to_sides: null, paise_per_side: paise }];

describe("money as the shopkeeper types it", () => {
  it("shows paise as rupees", () => {
    expect([200, 250, 5, 0, 12345].map(paiseToText)).toEqual(["2", "2.50", "0.05", "0", "123.45"]);
  });

  it("reads rupees as whole paise, and refuses what is not an amount", () => {
    expect(["2", "2.5", "2.50", "₹ 1,000", "0"].map(textToPaise)).toEqual([200, 250, 250, 100000, 0]);
    expect(["", "2.505", "-1", "two", "1e3", "99999999"].map(textToPaise)).toEqual([null, null, null, null, null, null]);
  });
});

describe("a price list and the form", () => {
  const slabs = [{ from_sides: 1, to_sides: 20, paise_per_side: 200 }, { from_sides: 21, to_sides: null, paise_per_side: 150 }];

  it("goes to the form and back unchanged", () => {
    const tiers = slabsToTiers(slabs);
    expect(tiers).toEqual([{ from: "1", price: "2" }, { from: "21", price: "1.50" }]);
    expect(tiersToSlabs(tiers, "X")).toEqual({ ok: true, slabs });
  });

  it("starts the first price at 1 side and leaves the last one open", () => {
    const r = tiersToSlabs([{ from: "", price: "3" }, { from: "11", price: "2" }, { from: "101", price: "1" }], "X");
    expect(r).toEqual({ ok: true, slabs: [
      { from_sides: 1, to_sides: 10, paise_per_side: 300 }, { from_sides: 11, to_sides: 100, paise_per_side: 200 }, { from_sides: 101, to_sides: null, paise_per_side: 100 }] });
  });

  it("says what is wrong in words", () => {
    const say = (tiers: { from: string; price: string }[]) => { const r = tiersToSlabs(tiers, "Black & white, one side"); return r.ok ? "ok" : r.error; };
    expect(say([{ from: "1", price: "" }])).toBe("Black & white, one side: enter a price.");
    expect(say([{ from: "1", price: "abc" }])).toBe("Black & white, one side: the price must be an amount in rupees, like 2 or 2.50.");
    expect(say([{ from: "1", price: "2" }, { from: "1", price: "1" }])).toBe("Black & white, one side: the second price must start after 1 side.");
    expect(say([{ from: "1", price: "2" }, { from: "20", price: "1" }, { from: "15", price: "1" }])).toBe("Black & white, one side: the third price must start after 20 sides.");
    expect(say([{ from: "1", price: "2" }, { from: "2.5", price: "1" }])).toBe("Black & white, one side: the second price needs a whole number of sides to start from.");
    expect(say([{ from: "1", price: "2" }, { from: "20", price: "" }])).toBe("Black & white, one side: enter the second price, or remove that line.");
  });
});

describe("the whole form", () => {
  it("becomes the two tables the server stores", () => {
    const form = tablesToForm({ simplex: flat(200), duplex: flat(120) }, { simplex: flat(1000), duplex: flat(800) });
    expect(formToTables(form, true)).toEqual({ ok: true, bw: { simplex: flat(200), duplex: flat(120) }, color: { simplex: flat(1000), duplex: flat(800) } });
  });

  it("a shop without colour saves with only black & white prices; colour takes the same prices", () => {
    const form = emptyForm();
    form["bw.simplex"][0].price = "2"; form["bw.duplex"][0].price = "1.50";
    expect(formToTables(form, true)).toEqual({ ok: false, error: "Colour, one side: enter a price." });
    expect(formToTables(form, false)).toEqual({ ok: true, bw: { simplex: flat(200), duplex: flat(150) }, color: { simplex: flat(200), duplex: flat(150) } });
  });

  it("keeps colour prices the shop already had while colour is off", () => {
    const form = tablesToForm({ simplex: flat(200), duplex: flat(120) }, { simplex: flat(1000), duplex: flat(800) });
    const r = formToTables(form, false);
    expect(r.ok && r.color).toEqual({ simplex: flat(1000), duplex: flat(800) });
  });
});
