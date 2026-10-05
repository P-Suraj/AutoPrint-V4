import { describe, expect, it } from "vitest";
import { normalizeShopCode } from "./shopCode";

describe("normalizeShopCode", () => {
  it.each([
    ["TST001", "TST001"],
    ["tst001", "TST001"],
    [" tst 001 ", "TST001"],
    ["TST-001", "TST001"],
    ["T5T001", "TST001"],      // a digit where a letter belongs
    ["TSTOO1", "TST001"],      // a letter O where a digit belongs
    ["TSTO0l", "TST001"],      // O and lower-case L where digits belong
    ["0ST001", "OST001"],
  ])("%s -> %s", (input, want) => {
    expect(normalizeShopCode(input)).toEqual({ code: want, valid: true });
  });

  it.each(["", "TST", "TST0012", "12", "TS!", "TST00"])("rejects %j", (input) => {
    expect(normalizeShopCode(input).valid).toBe(false);
  });

  it("does not invent a code from an impossible character", () => {
    expect(normalizeShopCode("TST0X1").valid).toBe(false);   // X cannot be a digit
    expect(normalizeShopCode("9ST001").valid).toBe(false);   // 9 has no letter twin
  });
});
