import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPatch, apiPost, RateLimitedError } from "../../src/api/client";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("api/client", () => {
  const originalAssign = window.location.assign;

  beforeEach(() => {
    document.cookie = "";
    // window.location.assign isn't implemented in jsdom by default.
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.assign = originalAssign;
  });

  it("attaches the CSRF header from the non-HttpOnly cookie on a mutating request", async () => {
    document.cookie = "csrf_token=abc123";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiPost("/api/admin/budget", { amount: "1.00" });

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("abc123");
  });

  it("does not attach a CSRF header on a GET request", async () => {
    document.cookie = "csrf_token=abc123";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/api/admin/budget");

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Headers;
    expect(headers.has("X-CSRF-Token")).toBe(false);
  });

  it("redirects to /login on a 401 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/me")).rejects.toThrow("unauthenticated");
    expect(window.location.assign).toHaveBeenCalledWith("/login");
  });

  it("throws a RateLimitedError with the parsed Retry-After on a 429 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 429,
        headers: { "Retry-After": "42" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiPatch("/api/admin/inventory/items/x", {}).catch((e) => e);
    expect(error).toBeInstanceOf(RateLimitedError);
    expect((error as RateLimitedError).retryAfterSeconds).toBe(42);
  });
});
