// The "Your order" card: the way back to an order after the tab was closed.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", async (original) => {
  const real = await original<typeof import("./api")>();
  return { ...real, api: { ...real.api, getOrder: vi.fn() } };
});

import { ApiError, api, type Schemas } from "./api";
import { YourOrders } from "./orders";
import { classifyPdfError } from "./preview";
import { rememberOrder, saveSecret, savedOrders } from "./store";

const getOrder = vi.mocked(api.getOrder);
const view = (status: string, message: string) => ({
  order_id: "id-1", short_code: "K7QD", shop_name: "Test Shop", status, approval_expires_at: null, payment_mode: null, payment_status: null,
  amount_paise: 600, can_cancel: false, jobs: [{ job_id: "j", document_name: "a.pdf", status: "completed", customer_message: message }],
}) as unknown as Schemas["OrderView"];
const show = (shopCode?: string) => render(<MemoryRouter><YourOrders shopCode={shopCode} /></MemoryRouter>);

beforeEach(() => {
  localStorage.clear(); getOrder.mockReset();
  saveSecret("id-1", "s1"); rememberOrder({ id: "id-1", code: "K7QD", shopCode: "TST001", shopName: "Test Shop" });
});
afterEach(cleanup);

describe("Your order card", () => {
  it("shows nothing when this phone has sent nothing", () => {
    localStorage.clear();
    const { container } = show();
    expect(container.textContent).toBe("");
    expect(getOrder).not.toHaveBeenCalled();
  });

  it("links back to the order with the server's own wording", async () => {
    getOrder.mockResolvedValue(view("closed", "Sent to printer. Collect it at the counter."));
    show();
    expect(screen.getByText("K7QD")).toBeTruthy();                            // shown at once, from the phone
    await waitFor(() => expect(screen.getByText("Sent to printer. Collect it at the counter.")).toBeTruthy());
    expect(screen.getByRole("link").getAttribute("href")).toBe("/o/id-1");
    expect(getOrder).toHaveBeenCalledWith("id-1", "s1");
  });

  it("disappears, and is dropped from the phone, when the server says the order is gone", async () => {
    getOrder.mockRejectedValue(new ApiError("order_not_found", "This order link is not valid any more.", 404));
    show();
    await waitFor(() => expect(screen.queryByText("K7QD")).toBeNull());
    expect(savedOrders()).toEqual([]);
  });

  it("stays, without inventing a status, when the server cannot be reached", async () => {
    getOrder.mockRejectedValue(new ApiError("network", "Could not reach AutoPrint."));
    show();
    await waitFor(() => expect(screen.getByText(/Could not check the status just now/)).toBeTruthy());
    expect(savedOrders()).toHaveLength(1);
  });

  it("on a shop's page shows only that shop's orders", () => {
    getOrder.mockResolvedValue(view("submitted", "Waiting for the shop to approve your print."));
    const { container } = show("ABC123");
    expect(container.textContent).toBe("");
  });
});

describe("what the browser can tell about a PDF before uploading", () => {
  it("knows a password-protected file and a broken file; anything else is not a statement about the file", () => {
    expect(classifyPdfError({ name: "PasswordException" }).kind).toBe("encrypted");
    expect(classifyPdfError({ name: "InvalidPDFException" }).kind).toBe("invalid");
    expect(classifyPdfError(new TypeError("Promise.withResolvers is not a function")).kind).toBe("unknown");
    expect(classifyPdfError(null).kind).toBe("unknown");
  });
});
