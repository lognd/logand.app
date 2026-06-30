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
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });

  if (res.status === 401) {
    // TODO(logan): wire to a real router navigation once auth flow exists.
    window.location.assign("/login");
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
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}
