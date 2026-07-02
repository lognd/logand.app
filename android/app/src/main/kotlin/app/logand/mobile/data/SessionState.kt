package app.logand.mobile.data

import app.logand.core.model.Me

sealed class SessionState {
    data object LoggedOut : SessionState()
    data class LoggedIn(val me: Me) : SessionState()

    // Distinct from LoggedOut -- a real login succeeded, but the account
    // is a "customer" role, and every route this app calls is
    // require_admin-gated on the backend (see api/mileage.py,
    // api/receipts.py). Kept separate so the UI can show "this app is
    // for admin accounts only" instead of silently bouncing back to the
    // login form as if the password were wrong.
    data class LoggedInWrongRole(val me: Me) : SessionState()
}
