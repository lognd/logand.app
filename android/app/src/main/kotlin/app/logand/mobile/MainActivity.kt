package app.logand.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.CreationExtras
import app.logand.mobile.ui.AppNavHost
import app.logand.mobile.ui.login.LoginViewModel
import app.logand.mobile.ui.mileage.MileageViewModel
import app.logand.mobile.ui.receipts.ReceiptsViewModel
import app.logand.mobile.ui.theme.LogandTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val loginViewModel: LoginViewModel by viewModels { viewModelFactory() }
    private val mileageViewModel: MileageViewModel by viewModels { viewModelFactory() }
    private val receiptsViewModel: ReceiptsViewModel by viewModels { viewModelFactory() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val container = (application as LogandApplication).container
        lifecycleScope.launch { container.initialize() }

        setContent {
            LogandTheme {
                AppNavHost(
                    loginViewModel = loginViewModel,
                    mileageViewModel = mileageViewModel,
                    receiptsViewModel = receiptsViewModel,
                )
            }
        }
    }

    private fun viewModelFactory(): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T {
            val container = (application as LogandApplication).container
            val apiClientProvider = { container.apiClient.value }
            return when (modelClass) {
                LoginViewModel::class.java ->
                    LoginViewModel(apiClientProvider, container.sessionState) as T
                MileageViewModel::class.java -> MileageViewModel(apiClientProvider) as T
                ReceiptsViewModel::class.java -> ReceiptsViewModel(apiClientProvider) as T
                else -> throw IllegalArgumentException("Unknown ViewModel class: $modelClass")
            }
        }
    }
}
