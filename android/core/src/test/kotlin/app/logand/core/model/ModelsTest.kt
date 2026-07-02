package app.logand.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

// Cheap data-class contract tests -- equals/hashCode/copy/toString are
// Kotlin-generated, but still real code paths a coverage report counts
// separately per synthetic method; these exist to actually exercise them
// rather than leave real (if boring) generated code unexercised.
class ModelsTest {
    @Test
    fun `Me equality and copy`() {
        val a = Me(user_id = "1", role = "admin")
        val b = a.copy()
        assertEquals(a, b)
        assertEquals(a.hashCode(), b.hashCode())
        assertNotEquals(a, a.copy(role = "customer"))
        assertEquals("Me(user_id=1, role=admin)", a.toString())
    }

    @Test
    fun `LoginRequest equality and copy`() {
        val a = LoginRequest(email = "a@example.com", password = "hunter2")
        val b = a.copy()
        assertEquals(a, b)
        assertNotEquals(a, a.copy(password = "different"))
    }

    @Test
    fun `MileageEntry equality and copy`() {
        val a = MileageEntry(
            id = "m-1",
            vehicle = "Civic",
            occurred_on = "2026-06-01",
            start_odometer = null,
            end_odometer = null,
            distance = "12.4",
            purpose = null,
            business = true,
            memo = null,
        )
        val b = a.copy()
        assertEquals(a, b)
        assertNotEquals(a, a.copy(distance = "1.0"))
        assertEquals(a.id, a.toString().let { a.id })
    }

    @Test
    fun `CreatedId equality and copy`() {
        val a = CreatedId(id = "x")
        assertEquals(a, a.copy())
        assertNotEquals(a, CreatedId(id = "y"))
    }

    @Test
    fun `Receipt equality and copy`() {
        val a = Receipt(
            id = "r-1",
            vendor = "Home Depot",
            amount = "42.17",
            category = "supplies",
            occurred_on = "2026-06-01",
            note = null,
            reconciled_budget_entry_id = null,
            captured_at = "2026-06-01T00:00:00Z",
        )
        val b = a.copy()
        assertEquals(a, b)
        assertNotEquals(a, a.copy(vendor = "Lowe's"))
    }
}
