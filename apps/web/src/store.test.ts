import { beforeEach, describe, expect, it } from "vitest";
import { clearDraft, forgetOrder, loadDraft, loadSecret, rememberOrder, saveDraft, saveSecret, savedOrders, type Draft } from "./store";

const order = (n: number) => ({ id: `id-${n}`, code: `K${n}QD`, shopCode: "TST001", shopName: "Test Shop" });

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });

describe("the orders this phone can go back to", () => {
  it("keeps a sent order, newest first, only while its secret is on the phone", () => {
    saveSecret("id-1", "s1"); rememberOrder(order(1));
    saveSecret("id-2", "s2"); rememberOrder(order(2));
    expect(savedOrders().map((o) => o.code)).toEqual(["K2QD", "K1QD"]);
    localStorage.removeItem("ap.order.id-2");
    expect(savedOrders().map((o) => o.code)).toEqual(["K1QD"]);
  });

  it("does not list the same order twice", () => {
    saveSecret("id-1", "s1"); rememberOrder(order(1)); rememberOrder(order(1));
    expect(savedOrders()).toHaveLength(1);
  });

  it("drops an order, and its secret, when the server says it is gone", () => {
    saveSecret("id-1", "s1"); rememberOrder(order(1));
    forgetOrder("id-1");
    expect(savedOrders()).toEqual([]);
    expect(loadSecret("id-1")).toBeNull();
  });

  it("is not a history: only a handful are kept, and the secret of a dropped one goes with it", () => {
    for (let n = 1; n <= 7; n++) { saveSecret(`id-${n}`, `s${n}`); rememberOrder(order(n)); }
    expect(savedOrders().map((o) => o.id)).toEqual(["id-7", "id-6", "id-5", "id-4", "id-3"]);
    expect(loadSecret("id-1")).toBeNull();
    expect(loadSecret("id-3")).toBe("s3");
  });

  it("ignores damaged storage instead of breaking the page", () => {
    localStorage.setItem("ap.orders", "{not json");
    expect(savedOrders()).toEqual([]);
    localStorage.setItem("ap.orders", JSON.stringify([{ id: 5 }, null, "x"]));
    expect(savedOrders()).toEqual([]);
  });
});

describe("the file being prepared in this tab", () => {
  const draft: Draft = { shopCode: "TST001", orderId: "id-1", shortCode: "K1QD", documentId: "doc-1", pageCount: 3, fileName: "a.pdf", copies: 2, color: false, duplex: true, pageRange: "1-2" };

  it("comes back after a refresh, for the same shop only", () => {
    saveSecret("id-1", "s1"); saveDraft(draft);
    expect(loadDraft("TST001")).toEqual(draft);
    expect(loadDraft("ABC123")).toBeNull();
  });

  it("is useless without the order secret, so it is not returned", () => {
    saveDraft(draft);
    expect(loadDraft("TST001")).toBeNull();
  });

  it("is gone once cleared (the order was sent, or another file was chosen)", () => {
    saveSecret("id-1", "s1"); saveDraft(draft); clearDraft();
    expect(loadDraft("TST001")).toBeNull();
  });
});
