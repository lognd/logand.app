package app.logand.core.model

import kotlinx.serialization.Serializable

// Field names match api/health.py's real MeResponse exactly (user_id/role,
// no email) -- see backend's api/auth.ts doc comment on the frontend for
// the exact same "don't guess the shape, verify it" lesson this mirrors.
@Serializable
data class Me(
    val user_id: String,
    val role: String,
)

@Serializable
data class LoginRequest(
    val email: String,
    val password: String,
)
