// The status page's promises: it keeps asking, survives a bad connection, stops at the end, and stays quiet while hidden.
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async (original) => {
  const real = await original<typeof import("../api")>();
  return { ...real, api: { ...real.api, getOrder: vi.fn(), cancelOrder: vi.fn() } };
});

import { ApiError, api, type Schemas } from "../api";
import { rememberOrder, saveSecret, savedOrders } from "../store";
import OrderPage, { POLL_MS, POLL_SLOW_AFTER_MS, POLL_SLOW_MS, RETRY_MAX_MS } from "./OrderPage";

const getOrder = vi.mocked(api.getOrder);
const ID = "11111111-2222-3333-4444-555555555555";
type Job = Schemas["OrderJobView"]["status"];
const MESSAGE: Partial<Record<Job, string>> = {
  awaiting_approval: "Waiting for the shop to approve your print.", approved: "Approved. Waiting for the printer.",
  completed: "Sent to printer. Collect it at the counter.", cancelled: "Cancelled.",
};
const view = (status: Schemas["OrderView"]["status"], job: Job): Schemas["OrderView"] => ({
  order_id: ID, short_code: "K7QD", shop_name: "Test Shop", status, approval_expires_at: null, payment_mode: "pay_at_counter",
  payment_status: null, amount_paise: 600, can_cancel: job === "awaiting_approval",
  jobs: [{ job_id: "j1", document_name: "notes.pdf", status: job, customer_message: MESSAGE[job] ?? job }],
} as Schemas["OrderView"]);

let hidden = false;
const setHidden = (h: boolean) => { hidden = h; document.dispatchEvent(new Event("visibilitychange")); };
const open = () => render(<MemoryRouter initialEntries={[`/o/${ID}`]}><Routes><Route path="/o/:orderId" element={<OrderPage />} /></Routes></MemoryRouter>);
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  saveSecret(ID, "secret");
  hidden = false;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
  getOrder.mockReset();
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("order status page", () => {
  it("shows what the server says and asks again every few seconds", async () => {
    getOrder.mockResolvedValue(view("submitted", "awaiting_approval"));
    open();
    await tick(0);
    expect(screen.getByText("Waiting for the shop to approve your print.")).toBeTruthy();
    expect(screen.getByText("K7QD")).toBeTruthy();
    await tick(POLL_MS * 3);
    expect(getOrder).toHaveBeenCalledTimes(4);
  });

  it("stops asking once the order is finished, and never says Printed", async () => {
    getOrder.mockResolvedValueOnce(view("submitted", "approved")).mockResolvedValue(view("closed", "completed"));
    open();
    await tick(0);
    await tick(POLL_MS);
    expect(screen.getByText("Sent to printer. Collect it at the counter.")).toBeTruthy();
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/\bprinted\b/);         // decision O-8
    const calls = getOrder.mock.calls.length;
    await tick(60_000);
    setHidden(true); setHidden(false);
    await tick(0);
    expect(getOrder).toHaveBeenCalledTimes(calls);
  });

  it("keeps the last view through a bad connection, says so, and recovers by itself", async () => {
    getOrder.mockResolvedValueOnce(view("submitted", "awaiting_approval"));
    getOrder.mockRejectedValueOnce(new ApiError("network", "Could not reach AutoPrint."));
    getOrder.mockRejectedValueOnce(new ApiError("internal_error", "Something went wrong on our side.", 500));
    getOrder.mockResolvedValue(view("submitted", "approved"));
    open();
    await tick(0);
    await tick(POLL_MS);                                   // first failure
    expect(screen.getByText(/Updates are delayed/)).toBeTruthy();
    expect(screen.getByText("Waiting for the shop to approve your print.")).toBeTruthy();
    await tick(POLL_MS * 2);                               // retried after 8 s: second failure
    await tick(POLL_MS * 4);                               // retried after 16 s: back
    expect(screen.getByText("Approved. Waiting for the printer.")).toBeTruthy();
    expect(screen.queryByText(/Updates are delayed/)).toBeNull();
  });

  it("never waits longer than the cap between tries, however long the connection is down", async () => {
    getOrder.mockRejectedValue(new ApiError("network", "Could not reach AutoPrint."));
    open();
    await tick(0);
    expect(screen.getByRole("alert").textContent).toMatch(/keeps trying/);                // not an endless silent spinner
    await tick(10 * 60_000);
    const before = getOrder.mock.calls.length;
    await tick(RETRY_MAX_MS);
    expect(getOrder.mock.calls.length).toBe(before + 1);
  });

  it("asks at once when the network comes back", async () => {
    getOrder.mockRejectedValueOnce(new ApiError("network", "down")).mockRejectedValueOnce(new ApiError("network", "down"));
    getOrder.mockResolvedValue(view("submitted", "awaiting_approval"));
    open();
    await tick(0);
    await tick(POLL_MS * 2);                               // two failures so far; the next try is 16 s away
    expect(getOrder).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await tick(0);
    expect(getOrder).toHaveBeenCalledTimes(3);
    expect(screen.getByText("Waiting for the shop to approve your print.")).toBeTruthy();
  });

  it("does not ask while the tab is hidden, and asks the moment it is seen again", async () => {
    getOrder.mockResolvedValue(view("submitted", "awaiting_approval"));
    open();
    await tick(0);
    expect(getOrder).toHaveBeenCalledTimes(1);
    await act(async () => { setHidden(true); });
    await tick(5 * 60_000);
    expect(getOrder).toHaveBeenCalledTimes(1);
    getOrder.mockResolvedValue(view("closed", "completed"));
    await act(async () => { setHidden(false); });
    await tick(0);
    expect(getOrder).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Sent to printer. Collect it at the counter.")).toBeTruthy();
  });

  it("asks less often after a long wait for the shop", async () => {
    getOrder.mockResolvedValue(view("submitted", "awaiting_approval"));
    open();
    await tick(0);
    await tick(POLL_SLOW_AFTER_MS + POLL_MS);
    const before = getOrder.mock.calls.length;
    await tick(POLL_SLOW_MS * 5);
    expect(getOrder.mock.calls.length - before).toBe(5);
  });

  it("an order the server no longer has is said plainly and dropped from the phone", async () => {
    rememberOrder({ id: ID, code: "K7QD", shopCode: "TST001", shopName: "Test Shop" });
    getOrder.mockRejectedValue(new ApiError("order_not_found", "This order link is not valid any more.", 404));
    open();
    await tick(0);
    expect(screen.getByRole("alert").textContent).toBe("This order link is not valid any more.");
    expect(savedOrders()).toEqual([]);
    await tick(60_000);
    expect(getOrder).toHaveBeenCalledTimes(1);
  });

  it("without the secret (another phone) it explains instead of asking the server", async () => {
    localStorage.clear();
    open();
    await tick(0);
    expect(screen.getByText(/can only be opened in the browser where it was started/)).toBeTruthy();
    expect(getOrder).not.toHaveBeenCalled();
  });

  it("asks for money and for the code only while there is something to collect", async () => {
    const asks = () => [screen.queryByText(/pay at the counter/) !== null, screen.queryByText("Say this code at the counter") !== null];
    getOrder.mockResolvedValue(view("submitted", "awaiting_approval"));
    open();
    await tick(0);
    expect(asks()).toEqual([true, true]);
    cleanup();
    for (const [order, job] of [["cancelled", "cancelled"], ["expired", "expired"], ["closed", "rejected"]] as const) {
      getOrder.mockResolvedValue(view(order, job));
      open();
      await tick(0);
      expect(asks()).toEqual([false, false]);
      cleanup();
    }
    getOrder.mockResolvedValue(view("closed", "failed"));          // "ask at the counter": the code still helps, the price does not
    open();
    await tick(0);
    expect(asks()).toEqual([false, true]);
  });
});
