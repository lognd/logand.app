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

class LoginViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    private val _session = MutableStateFlow<SessionState>(SessionState.LoggedOut)
    val session: StateFlow<SessionState> = _session.asStateFlow()

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
            when (val loginResult = client.login(state.email.trim(), state.password)) {
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
