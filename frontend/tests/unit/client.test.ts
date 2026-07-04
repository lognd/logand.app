import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPatch, apiPost, RateLimitedError } from "../../src/api/client";

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

  it("redirects to /login on a 401 from a protected endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/admin/invoices")).rejects.toThrow("unauthenticated");
    expect(window.location.assign).toHaveBeenCalledWith("/login");
  });

  it("does NOT redirect on a 401 from /api/me -- that's the passive logged-out check", async () => {
    // Every page mounts useMe() (Shell's nav, the guards) to find out
    // whether anyone's logged in; a 401 here is the normal answer for a
    // logged-out visitor, not an error to redirect on. Redirecting on it
    // previously caused a reload loop: every page (including /login
    // itself) mounts the nav, which calls /api/me, which 401s, which
    // redirected to /login, which mounts the nav again...
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/me")).rejects.toThrow("unauthenticated");
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("does NOT redirect on a 401 from /api/auth/login, and surfaces the real detail", async () => {
    // A wrong password on the login form itself 401s -- previously this
    // fell into the same "protected endpoint" branch as e.g.
    // /api/admin/invoices, triggering a full-page redirect to /login
    // (already the current page) before the login form's own error
    // handler ever ran, so the real "email or password is incorrect"
    // message from the backend was silently discarded.
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "email or password is incorrect" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiPost("/api/auth/login", {
      email: "x@example.com",
      password: "wrong",
    }).catch((e) => e);

    expect(window.location.assign).not.toHaveBeenCalled();
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("email or password is incorrect");
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
