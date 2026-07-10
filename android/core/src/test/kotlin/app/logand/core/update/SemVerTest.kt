package app.logand.core.update

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SemVerTest {
    @Test
    fun `parses a bare vX Y Z tag`() {
        val version = parseSemVer("v1.2.3")
        assertEquals(SemVer(1, 2, 3), version)
    }

    @Test
    fun `parses a tag with no leading v`() {
        assertEquals(SemVer(1, 0, 1), parseSemVer("1.0.1"))
    }

    @Test
    fun `parses a tag with a pre-release suffix, ignoring the suffix`() {
        assertEquals(SemVer(2, 0, 0), parseSemVer("v2.0.0-beta.1"))
    }

    @Test
    fun `returns null for a malformed tag`() {
        assertNull(parseSemVer("not-a-version"))
        assertNull(parseSemVer("v1.2"))
        assertNull(parseSemVer(""))
    }

    @Test
    fun `numeric comparison, not lexicographic -- v1 10 0 beats v1 9 0`() {
        val v1_10_0 = parseSemVer("v1.10.0")!!
        val v1_9_0 = parseSemVer("v1.9.0")!!
        assertTrue(v1_10_0 > v1_9_0)
    }

    @Test
    fun `equal versions compare equal`() {
        assertEquals(0, parseSemVer("v1.2.3")!!.compareTo(parseSemVer("1.2.3")!!))
    }

    @Test
    fun `patch then minor then major break ties in order`() {
        assertTrue(SemVer(1, 0, 1) > SemVer(1, 0, 0))
        assertTrue(SemVer(1, 1, 0) > SemVer(1, 0, 9))
        assertTrue(SemVer(2, 0, 0) > SemVer(1, 99, 99))
    }
}
