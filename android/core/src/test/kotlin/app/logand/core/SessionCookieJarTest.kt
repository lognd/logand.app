package app.logand.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import okhttp3.Cookie
import okhttp3.HttpUrl.Companion.toHttpUrl

class SessionCookieJarTest {
    private val url = "https://example.com/".toHttpUrl()

    @Test
    fun `value returns null before any cookie has been saved`() {
        val jar = SessionCookieJar()
        assertNull(jar.value("csrf_token"))
    }

    @Test
    fun `saveFromResponse then value round-trips a cookie by name`() {
        val jar = SessionCookieJar()
        val cookie = Cookie.Builder()
            .name("csrf_token")
            .value("abc123")
            .domain("example.com")
            .build()

        jar.saveFromResponse(url, listOf(cookie))

        assertEquals("abc123", jar.value("csrf_token"))
    }

    @Test
    fun `loadForRequest returns every stored cookie`() {
        val jar = SessionCookieJar()
        jar.saveFromResponse(
            url,
            listOf(
                Cookie.Builder().name("a").value("1").domain("example.com").build(),
                Cookie.Builder().name("b").value("2").domain("example.com").build(),
            ),
        )

        val loaded = jar.loadForRequest(url)

        assertEquals(setOf("a", "b"), loaded.map { it.name }.toSet())
    }

    @Test
    fun `a later cookie with the same name overwrites the earlier one`() {
        val jar = SessionCookieJar()
        jar.saveFromResponse(
            url,
            listOf(Cookie.Builder().name("csrf_token").value("old").domain("example.com").build()),
        )
        jar.saveFromResponse(
            url,
            listOf(Cookie.Builder().name("csrf_token").value("new").domain("example.com").build()),
        )

        assertEquals("new", jar.value("csrf_token"))
    }

    @Test
    fun `loadForRequest does not return cookies saved for a different host`() {
        val jar = SessionCookieJar()
        jar.saveFromResponse(
            url,
            listOf(Cookie.Builder().name("csrf_token").value("abc").domain("example.com").build()),
        )

        val otherHostUrl = "https://evil.example/".toHttpUrl()
        val loaded = jar.loadForRequest(otherHostUrl)

        assertEquals(emptyList(), loaded)
        // Direct-by-name reads (used for the CSRF header) are unaffected --
        // they aren't host-scoped, only the cookies OkHttp attaches to
        // outgoing requests are.
        assertEquals("abc", jar.value("csrf_token"))
    }

    @Test
    fun `clear removes every stored cookie`() {
        val jar = SessionCookieJar()
        jar.saveFromResponse(
            url,
            listOf(Cookie.Builder().name("csrf_token").value("abc").domain("example.com").build()),
        )

        jar.clear()

        assertNull(jar.value("csrf_token"))
        assertEquals(emptyList(), jar.loadForRequest(url))
    }
}
