// The only place the browser talks to the API. Types come from the generated contract
// (contracts/clients/ts/schema.d.ts), so a contract change is a compile error, not a runtime surprise.
import createClient from "openapi-fetch";
import type { components, paths } from "../../../contracts/clients/ts/schema";

export type Schemas = components["schemas"];

const client = createClient<paths>({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? "" });

/** An error from the API, or from the network. `code` comes from the server's error catalog. */
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) {
    super(message);
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>(r: Result<T>): T {
  if (r.data !== undefined) return r.data;
  const body = r.error as { error?: { code?: string; message?: string } } | undefined;
  const e = body?.error;
  throw new ApiError(e?.code ?? "unknown", e?.message ?? "Something went wrong. Please try again.", r.response?.status ?? 0);
}

/** Network failure (offline, DNS, blocked): never shown as success, never replaced with fake data. */
async function call<T>(fn: () => Promise<Result<T>>): Promise<T> {
  try {
    return unwrap(await fn());
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError("network", "Could not reach AutoPrint. Check your connection and try again.");
  }
}

const secretHeader = (secret: string) => ({ "X-Order-Secret": secret });

export const api = {
  getShop: (code: string) => call(() => client.GET("/v1/shops/{shop_code}", { params: { path: { shop_code: code } } })),
  getRates: (code: string) => call(() => client.GET("/v1/shops/{shop_code}/rates", { params: { path: { shop_code: code } } })),
  createOrder: (code: string) => call(() => client.POST("/v1/shops/{shop_code}/orders", { params: { path: { shop_code: code } } })),
  registerDocument: (orderId: string, secret: string, body: Schemas["RegisterDocumentRequest"]) =>
    call(() => client.POST("/v1/orders/{order_id}/documents", { params: { path: { order_id: orderId }, header: { "x-order-secret": secret } }, body })),
  finalizeDocument: (orderId: string, documentId: string, secret: string) =>
    call(() => client.POST("/v1/orders/{order_id}/documents/{document_id}/finalize",
      { params: { path: { order_id: orderId, document_id: documentId }, header: { "x-order-secret": secret } } })),
  createQuote: (orderId: string, secret: string, body: Schemas["CreateQuoteRequest"]) =>
    call(() => client.POST("/v1/orders/{order_id}/quote", { params: { path: { order_id: orderId }, header: { "x-order-secret": secret } }, body })),
  submitOrder: (orderId: string, secret: string, quoteId: string) =>
    call(() => client.POST("/v1/orders/{order_id}/submit", { params: { path: { order_id: orderId }, header: { "x-order-secret": secret } }, body: { quote_id: quoteId } })),
  cancelOrder: (orderId: string, secret: string) =>
    call(() => client.POST("/v1/orders/{order_id}/cancel", { params: { path: { order_id: orderId }, header: { "x-order-secret": secret } } })),
  getOrder: (orderId: string, secret: string) =>
    call(() => client.GET("/v1/orders/{order_id}", { params: { path: { order_id: orderId }, header: { "x-order-secret": secret } } })),
};

/**
 * Upload the PDF with a raw PUT to the signed URL.
 * Never FormData: V3 sent multipart to a raw upload URL and the stored file was not a PDF.
 */
export function uploadPdf(url: string, headers: Record<string, string>, file: File, onProgress?: (fraction: number) => void): Promise<void> {
  // XMLHttpRequest, not fetch: it is the only way a browser reports how much of an upload has been sent.
  return new Promise((resolve, reject) => {
    const interrupted = () => reject(new ApiError("network", "The upload was interrupted. Check your connection and try again."));
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    if (onProgress) xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new ApiError("upload_failed", "The upload did not complete. Please try again.", xhr.status)));
    xhr.onerror = interrupted; xhr.onabort = interrupted; xhr.ontimeout = interrupted;
    xhr.send(file);
  });
}

export { secretHeader };

// ---- shop owner dashboard (/shop). The key comes from the private link and is kept in this browser only.
const shopKey = (key: string) => ({ "X-Shop-Key": key });

export const shopApi = {
  me: (key: string) => call(() => client.GET("/v1/shop/me", { params: { header: { "x-shop-key": key } } })),
  lookup: (key: string, code: string) =>
    call(() => client.GET("/v1/shop/pair/{pair_code}", { params: { path: { pair_code: code }, header: { "x-shop-key": key } } })),
  approve: (key: string, code: string) =>
    call(() => client.POST("/v1/shop/pair/approve", { params: { header: { "x-shop-key": key } }, body: { pair_code: code } })),
  devices: (key: string) => call(() => client.GET("/v1/shop/devices", { params: { header: { "x-shop-key": key } } })),
  revoke: (key: string, id: string) =>
    call(() => client.POST("/v1/shop/devices/{device_id}/revoke", { params: { path: { device_id: id }, header: { "x-shop-key": key } } })),
};
export { shopKey };

// ---- sign-in by email (no key needed: these two calls are how a shopkeeper gets one)
export const shopAuth = {
  emailStart: (email: string) => call(() => client.POST("/v1/shop/email/start", { body: { email } })),
  emailFinish: (accessToken: string) => call(() => client.POST("/v1/shop/email/finish", { body: { access_token: accessToken } })),
};
