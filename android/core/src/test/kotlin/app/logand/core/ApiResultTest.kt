package app.logand.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ApiResultTest {
    @Test
    fun `map transforms a Success value`() {
        val result: ApiResult<Int> = ApiResult.Success(2)

        val mapped = result.map { it * 21 }

        assertIs<ApiResult.Success<Int>>(mapped)
        assertEquals(42, mapped.data)
    }

    @Test
    fun `map passes through HttpError untouched`() {
        val result: ApiResult<Int> = ApiResult.HttpError(404, "not found")

        val mapped = result.map { it * 21 }

        assertIs<ApiResult.HttpError>(mapped)
        assertEquals(404, mapped.statusCode)
        assertEquals("not found", mapped.message)
    }

    @Test
    fun `map passes through NetworkError untouched`() {
        val cause = RuntimeException("boom")
        val result: ApiResult<Int> = ApiResult.NetworkError(cause)

        val mapped = result.map { it * 21 }

        assertIs<ApiResult.NetworkError>(mapped)
        assertEquals(cause, mapped.cause)
    }
}
