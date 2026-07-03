package app.logand.mobile.ui.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.mobile.data.SessionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class LoginUiState(
    val email: String = "",
    val password: String = "",
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
)

class LoginViewModel(
    private val apiClient: () -> ApiClient,
    // AppContainer's app-wide "did ANY call just come back 401" signal --
    // see AppContainer.sessionState's doc comment. Collected below so a
    // mid-session expiry/revocation (idle timeout, "kill all sessions")
    // flips THIS ViewModel's `session` -- the one AppNavHost actually
    // reads to pick LoggedOut/LoggedIn/WrongRole -- instead of only
    // flipping AppContainer's own copy while the UI keeps rendering
    // MainTabs as if nothing happened.
    containerSessionState: StateFlow<SessionState>? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    private val _session = MutableStateFlow<SessionState>(SessionState.LoggedOut)
    val session: StateFlow<SessionState> = _session.asStateFlow()

    init {
        if (containerSessionState != null) {
            viewModelScope.launch {
                containerSessionState.collect { containerState ->
                    if (containerState is SessionState.LoggedOut &&
                        _session.value !is SessionState.LoggedOut
                    ) {
                        _session.value = SessionState.LoggedOut
                    }
                }
            }
        }
    }

    fun onEmailChange(value: String) {
        _uiState.value = _uiState.value.copy(email = value, errorMessage = null)
    }

    fun onPasswordChange(value: String) {
        _uiState.value = _uiState.value.copy(password = value, errorMessage = null)
    }

    fun login() {
        val state = _uiState.value
        if (state.email.isBlank() || state.password.isBlank()) {
            _uiState.value = state.copy(errorMessage = "Email and password are required.")
            return
        }
        _uiState.value = state.copy(isLoading = true, errorMessage = null)
        viewModelScope.launch {
            val client = apiClient()
            // Lowercased, not just trimmed -- the backend's own login
            // lookup normalizes stored/looked-up emails the same way
            // (register()/ensure_admin_seeded() both store
            // email.strip().lower()); sending mixed case here relied on
            // that normalization existing server-side too, which wasn't
            // always true. Matching it here means this client never
            // depends on that backend behavior being correct to log a
            // real user in.
            val normalizedEmail = state.email.trim().lowercase()
            when (val loginResult = client.login(normalizedEmail, state.password)) {
                is ApiResult.Success -> refreshSessionAfterLogin(client)
                is ApiResult.HttpError -> fail(loginResult.message)
                is ApiResult.NetworkError -> fail("Could not reach the server. Check your connection.")
            }
        }
    }

    private suspend fun refreshSessionAfterLogin(client: ApiClient) {
        when (val meResult = client.me()) {
            is ApiResult.Success -> {
                _session.value = if (meResult.data.role == "admin") {
                    SessionState.LoggedIn(meResult.data)
                } else {
                    SessionState.LoggedInWrongRole(meResult.data)
                }
                _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = null)
            }
            is ApiResult.HttpError -> fail(meResult.message)
            is ApiResult.NetworkError -> fail("Could not reach the server. Check your connection.")
        }
    }

    private fun fail(message: String) {
        _uiState.value = _uiState.value.copy(isLoading = false, errorMessage = message)
    }

    fun logout() {
        viewModelScope.launch {
            apiClient().logout()
            _session.value = SessionState.LoggedOut
            _uiState.value = LoginUiState()
        }
    }
}
