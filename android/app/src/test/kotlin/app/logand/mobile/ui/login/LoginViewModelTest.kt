package app.logand.mobile.ui.login

import app.logand.core.ApiClient
import app.logand.mobile.data.SessionState
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

// Real ApiClient against a real MockWebServer, not a mocked ApiClient --
// verifies LoginViewModel's actual state transitions in response to real
// HTTP responses, same "real infra over mocks" convention as :core's own
// ApiClientTest.
//
// Dispatchers.Main is set to the real Dispatchers.Unconfined (not a
// virtual-time TestDispatcher) deliberately -- login()/logout() launch
// fire-and-forget coroutines on viewModelScope that are NOT children of
// this test's own coroutine, so there is nothing for runTest's virtual
// clock to "advance until idle" on. Real time + polling (awaitState
// below) is the honest, reliable way to wait for that real, independently
// -scheduled work to finish.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class LoginViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: LoginViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = LoginViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (LoginUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `blank email or password is rejected before any network call`() = runBlocking {
        viewModel.onEmailChange("")
        viewModel.onPasswordChange("")

        viewModel.login()

        assertEquals("Email and password are required.", viewModel.uiState.value.errorMessage)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `successful login and admin me() transitions session to LoggedIn`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"user_id":"1","role":"admin"}""")
        )
        viewModel.onEmailChange("admin@logand.app")
        viewModel.onPasswordChange("hunter2")

        viewModel.login()
        awaitState { !it.isLoading }

        val session = viewModel.session.value
        assertIs<SessionState.LoggedIn>(session)
        assertEquals("admin", session.me.role)
    }

    @Test
    fun `login as a customer account surfaces LoggedInWrongRole, not LoggedIn`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"user_id":"2","role":"customer"}""")
        )
        viewModel.onEmailChange("customer@example.com")
        viewModel.onPasswordChange("hunter2")

        viewModel.login()
        awaitState { !it.isLoading }

        assertIs<SessionState.LoggedInWrongRole>(viewModel.session.value)
    }

    @Test
    fun `wrong password surfaces the backend's error message`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(401)
                .setBody("""{"detail":"email or password is incorrect"}""")
        )
        viewModel.onEmailChange("admin@logand.app")
        viewModel.onPasswordChange("wrong")

        viewModel.login()
        awaitState { !it.isLoading }

        assertEquals("email or password is incorrect", viewModel.uiState.value.errorMessage)
        assertIs<SessionState.LoggedOut>(viewModel.session.value)
    }

    @Test
    fun `logout resets both session and form state`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"user_id":"1","role":"admin"}""")
        )
        viewModel.onEmailChange("admin@logand.app")
        viewModel.onPasswordChange("hunter2")
        viewModel.login()
        awaitState { !it.isLoading }

        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        viewModel.logout()
        awaitState { it.email.isEmpty() }

        assertIs<SessionState.LoggedOut>(viewModel.session.value)
    }
}
