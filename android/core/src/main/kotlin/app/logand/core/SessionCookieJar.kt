package app.logand.core

import java.util.concurrent.ConcurrentHashMap
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

// In-memory, single-host cookie jar -- this app only ever talks to one
// backend, so there's no need for the full per-domain matching a browser
// cookie jar does. Deliberately accepts cookies regardless of their
// Secure/SameSite attributes: those are BROWSER enforcement concepts
// (see docs/design/14-mileage-receipts-documents.md's note that CORS/
// SameSite don't apply to a native HTTP client at all) -- a real mobile
// client just stores and resends whatever the server set, the same way
// curl or any other non-browser HTTP client would.
//
// L2 in FINDINGS.md: loadForRequest used to hand back every stored
// cookie regardless of `url`, so a cross-host 3xx redirect from the
// (user-configurable, see ServerSettingsRepository) backend host would
// carry the session cookie to whatever host the redirect pointed at --
// OkHttp follows redirects by default. Each cookie's origin host is now
// tracked at saveFromResponse time and loadForRequest only returns
// cookies whose stored host matches the request's host.
class SessionCookieJar : CookieJar {
    private data class HostedCookie(val cookie: Cookie, val host: String)

    private val cookies = ConcurrentHashMap<String, HostedCookie>()

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        for (cookie in cookies) {
            this.cookies[cookie.name] = HostedCookie(cookie, url.host)
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> =
        cookies.values.filter { it.host == url.host }.map { it.cookie }

    // Read directly by name -- api/auth.py's CSRF_COOKIE_NAME
    // ("csrf_token") is deliberately httponly=false specifically so a
    // client (browser JS, or this cookie jar) can read it back and set
    // it as the X-CSRF-Token header on mutating requests (double-submit
    // pattern, see backend's auth/csrf.py).
    fun value(name: String): String? = cookies[name]?.cookie?.value

    fun clear() {
        cookies.clear()
    }
}
