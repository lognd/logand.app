// The only module allowed to call fetch() directly -- see docs/design/07.
// Session cookie is HttpOnly and never touched here; only the non-HttpOnly
// CSRF cookie is read, per docs/design/02-auth-and-security.md.

export class RateLimitedError extends Error {
  constructor(public readonly retryAfterSeconds: number) {
    super(`Rate limited, retry after ${retryAfterSeconds}s`);
  }
}

function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isMutating = !!init.method && init.method !== "GET";
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (isMutating) {
    const csrf = readCsrfCookie();
    if (csrf) headers.set("X-CSRF-Token", csrf);
    // FormData (file uploads, see api/budget.ts's uploadBudgetEvidence)
    // must NOT get an explicit Content-Type -- the browser sets its own
    // multipart/form-data boundary parameter when the body is a raw
    // FormData object, and overriding it with a plain
    // "multipart/form-data" (no boundary) breaks the request server-side.
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });

  if (res.status === 401) {
    // /api/me is a passive "are you logged in?" check -- every page mounts
    // it via useMe() (Shell's nav, AdminGuard, CustomerGuard) and a 401
    // from it is the NORMAL, expected response for a logged-out visitor on
    // a public page, not an error condition. Redirecting on it caused a
    // hard reload loop: every page (including /login itself) mounts the
    // nav, which calls /api/me, which 401s, which redirected to /login,
    // which mounts the nav again, which 401s again... Real protected
    // endpoints (admin/customer data fetches) still redirect on 401 --
    // only this passive check is exempt.
    if (path !== "/api/me") {
      window.location.assign("/login");
    }
    throw new Error("unauthenticated");
  }

  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After") ?? "1");
    throw new RateLimitedError(retryAfter);
  }

  if (!res.ok) {
    throw new Error(`request failed: ${res.status} ${res.statusText}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}
