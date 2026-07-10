package app.logand.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.CreationExtras
import app.logand.core.update.UpdateChecker
import app.logand.mobile.ui.AdminViewModels
import app.logand.mobile.ui.AppNavHost
import app.logand.mobile.ui.admin.bom.BomViewModel
import app.logand.mobile.ui.admin.budget.BudgetViewModel
import app.logand.mobile.ui.admin.customers.CustomersViewModel
import app.logand.mobile.ui.admin.data.AdminDataViewModel
import app.logand.mobile.ui.admin.inventory.InventoryViewModel
import app.logand.mobile.ui.admin.invoices.InvoicesViewModel
import app.logand.mobile.ui.admin.logs.AdminLogsViewModel
import app.logand.mobile.ui.admin.stats.StatsViewModel
import app.logand.mobile.ui.admin.version.AdminVersionViewModel
import app.logand.mobile.ui.login.LoginViewModel
import app.logand.mobile.ui.mileage.MileageViewModel
import app.logand.mobile.ui.receipts.ReceiptsViewModel
import app.logand.mobile.ui.theme.LogandTheme
import app.logand.mobile.ui.update.UpdateViewModel
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val loginViewModel: LoginViewModel by viewModels { viewModelFactory() }
    private val mileageViewModel: MileageViewModel by viewModels { viewModelFactory() }
    private val receiptsViewModel: ReceiptsViewModel by viewModels { viewModelFactory() }
    private val updateViewModel: UpdateViewModel by viewModels { viewModelFactory() }
    private val invoicesViewModel: InvoicesViewModel by viewModels { viewModelFactory() }
    private val customersViewModel: CustomersViewModel by viewModels { viewModelFactory() }
    private val statsViewModel: StatsViewModel by viewModels { viewModelFactory() }
    private val inventoryViewModel: InventoryViewModel by viewModels { viewModelFactory() }
    private val bomViewModel: BomViewModel by viewModels { viewModelFactory() }
    private val budgetViewModel: BudgetViewModel by viewModels { viewModelFactory() }
    private val adminDataViewModel: AdminDataViewModel by viewModels { viewModelFactory() }
    private val adminLogsViewModel: AdminLogsViewModel by viewModels { viewModelFactory() }
    private val adminVersionViewModel: AdminVersionViewModel by viewModels { viewModelFactory() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val container = (application as LogandApplication).container
        lifecycleScope.launch { container.initialize() }

        setContent {
            LogandTheme {
                AppNavHost(
                    loginViewModel = loginViewModel,
                    viewModels = AdminViewModels(
                        mileage = mileageViewModel,
                        receipts = receiptsViewModel,
                        invoices = invoicesViewModel,
                        customers = customersViewModel,
                        stats = statsViewModel,
                        inventory = inventoryViewModel,
                        bom = bomViewModel,
                        budget = budgetViewModel,
                        adminData = adminDataViewModel,
                        adminLogs = adminLogsViewModel,
                        adminVersion = adminVersionViewModel,
                    ),
                    updateViewModel = updateViewModel,
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
                    LoginViewModel(
                        apiClientProvider,
                        container.logoutEvents,
                        resetLogoutEvents = container::resetLogoutEvents,
                    ) as T
                MileageViewModel::class.java -> MileageViewModel(apiClientProvider) as T
                ReceiptsViewModel::class.java -> ReceiptsViewModel(apiClientProvider) as T
                InvoicesViewModel::class.java -> InvoicesViewModel(apiClientProvider) as T
                CustomersViewModel::class.java -> CustomersViewModel(apiClientProvider) as T
                StatsViewModel::class.java -> StatsViewModel(apiClientProvider) as T
                InventoryViewModel::class.java ->
                    InventoryViewModel(apiClientProvider, container.logger) as T
                BomViewModel::class.java ->
                    BomViewModel(apiClientProvider, container.logger) as T
                BudgetViewModel::class.java ->
                    BudgetViewModel(apiClientProvider, container.logger) as T
                AdminDataViewModel::class.java ->
                    AdminDataViewModel(apiClientProvider, container.logger) as T
                AdminLogsViewModel::class.java ->
                    AdminLogsViewModel(apiClientProvider, container.logger) as T
                AdminVersionViewModel::class.java ->
                    AdminVersionViewModel(apiClientProvider, container.logger) as T
                UpdateViewModel::class.java -> UpdateViewModel(
                    updateChecker = UpdateChecker(logger = container.logger),
                    currentVersion = BuildConfig.VERSION_NAME,
                    logger = container.logger,
                ) as T
                else -> throw IllegalArgumentException("Unknown ViewModel class: $modelClass")
            }
        }
    }
}
