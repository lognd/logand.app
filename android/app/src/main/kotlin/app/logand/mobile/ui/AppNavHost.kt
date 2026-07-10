package app.logand.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import app.logand.mobile.data.SessionState
import app.logand.mobile.ui.admin.bom.BomScreen
import app.logand.mobile.ui.admin.bom.BomViewModel
import app.logand.mobile.ui.admin.budget.BudgetScreen
import app.logand.mobile.ui.admin.budget.BudgetViewModel
import app.logand.mobile.ui.admin.customers.CustomersScreen
import app.logand.mobile.ui.admin.customers.CustomersViewModel
import app.logand.mobile.ui.admin.data.AdminDataScreen
import app.logand.mobile.ui.admin.data.AdminDataViewModel
import app.logand.mobile.ui.admin.inventory.InventoryScreen
import app.logand.mobile.ui.admin.inventory.InventoryViewModel
import app.logand.mobile.ui.admin.invoices.InvoicesScreen
import app.logand.mobile.ui.admin.invoices.InvoicesViewModel
import app.logand.mobile.ui.admin.logs.AdminLogsScreen
import app.logand.mobile.ui.admin.logs.AdminLogsViewModel
import app.logand.mobile.ui.admin.stats.StatsScreen
import app.logand.mobile.ui.admin.stats.StatsViewModel
import app.logand.mobile.ui.admin.version.AdminVersionScreen
import app.logand.mobile.ui.admin.version.AdminVersionViewModel
import app.logand.mobile.ui.login.LoginScreen
import app.logand.mobile.ui.login.LoginViewModel
import app.logand.mobile.ui.mileage.MileageScreen
import app.logand.mobile.ui.mileage.MileageViewModel
import app.logand.mobile.ui.receipts.ReceiptsScreen
import app.logand.mobile.ui.receipts.ReceiptsViewModel
import app.logand.mobile.ui.theme.SpacingLarge
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.update.UpdateBanner
import app.logand.mobile.ui.update.UpdateViewModel
import kotlinx.coroutines.launch

// Eleven destinations do not fit a Material bottom NavigationBar (which
// tops out around five before labels collide), so this is a
// ModalNavigationDrawer instead. Order below is the order in the drawer:
// the two field-use screens (mileage/receipts -- the ones used away from
// a desk) first, then the admin surface in the same order the web app's
// sidebar lists it, so muscle memory transfers between the two clients.
private enum class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    MILEAGE("mileage", "Mileage", Icons.AutoMirrored.Filled.List),
    RECEIPTS("receipts", "Receipts", Icons.Default.Receipt),
    INVOICES("invoices", "Invoices", Icons.Default.Description),
    CUSTOMERS("customers", "Customers", Icons.Default.Person),
    STATS("stats", "Stats", Icons.Default.Info),
    INVENTORY("inventory", "Inventory", Icons.Default.Build),
    BOM("bom", "BOM", Icons.Default.Build),
    BUDGET("budget", "Budget", Icons.Default.DateRange),
    ADMIN_DATA("admin-data", "Data", Icons.Default.Settings),
    ADMIN_LOGS("admin-logs", "Logs", Icons.AutoMirrored.Filled.List),
    ADMIN_VERSION("admin-version", "Version", Icons.Default.Info),
}

/**
 * Every ViewModel the signed-in admin UI needs, bundled so `AppNavHost`'s
 * signature does not grow one parameter per screen (it would be eleven).
 */
class AdminViewModels(
    val mileage: MileageViewModel,
    val receipts: ReceiptsViewModel,
    val invoices: InvoicesViewModel,
    val customers: CustomersViewModel,
    val stats: StatsViewModel,
    val inventory: InventoryViewModel,
    val bom: BomViewModel,
    val budget: BudgetViewModel,
    val adminData: AdminDataViewModel,
    val adminLogs: AdminLogsViewModel,
    val adminVersion: AdminVersionViewModel,
)

@Composable
fun AppNavHost(
    loginViewModel: LoginViewModel,
    viewModels: AdminViewModels,
    updateViewModel: UpdateViewModel,
) {
    val session by loginViewModel.session.collectAsStateWithLifecycle()

    when (val current = session) {
        is SessionState.LoggedOut -> LoginScreen(loginViewModel)
        is SessionState.LoggedInWrongRole -> WrongRoleScreen(
            role = current.me.role,
            onLogout = loginViewModel::logout,
        )
        is SessionState.LoggedIn -> MainScaffold(
            onLogout = loginViewModel::logout,
            viewModels = viewModels,
            updateViewModel = updateViewModel,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainScaffold(
    onLogout: () -> Unit,
    viewModels: AdminViewModels,
    updateViewModel: UpdateViewModel,
) {
    val navController = rememberNavController()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                val backStackEntry by navController.currentBackStackEntryAsState()
                val currentDestination = backStackEntry?.destination
                Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                    Text(
                        "logand.app",
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.padding(SpacingLarge),
                    )
                    Destination.entries.forEach { destination ->
                        NavigationDrawerItem(
                            selected = currentDestination?.hierarchy
                                ?.any { it.route == destination.route } == true,
                            onClick = {
                                scope.launch { drawerState.close() }
                                navController.navigate(destination.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = {
                                Icon(destination.icon, contentDescription = destination.label)
                            },
                            label = { Text(destination.label) },
                            modifier = Modifier.padding(horizontal = SpacingMedium),
                        )
                    }
                }
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("logand.app") },
                    navigationIcon = {
                        IconButton(
                            onClick = { scope.launch { drawerState.open() } },
                            modifier = Modifier.semantics {
                                contentDescription = "open navigation drawer"
                            },
                        ) { Icon(Icons.Default.Menu, contentDescription = null) }
                    },
                    actions = {
                        TextButton(
                            onClick = onLogout,
                            modifier = Modifier.semantics { contentDescription = "log out" },
                        ) { Text("Log out") }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                    ),
                )
            },
        ) { padding ->
            Column(modifier = Modifier.padding(padding)) {
                UpdateBanner(updateViewModel)
                NavHost(
                    navController = navController,
                    startDestination = Destination.MILEAGE.route,
                    modifier = Modifier.weight(1f),
                ) {
                    composable(Destination.MILEAGE.route) { MileageScreen(viewModels.mileage) }
                    composable(Destination.RECEIPTS.route) { ReceiptsScreen(viewModels.receipts) }
                    composable(Destination.INVOICES.route) { InvoicesScreen(viewModels.invoices) }
                    composable(Destination.CUSTOMERS.route) {
                        CustomersScreen(viewModels.customers)
                    }
                    composable(Destination.STATS.route) { StatsScreen(viewModels.stats) }
                    composable(Destination.INVENTORY.route) {
                        InventoryScreen(viewModels.inventory)
                    }
                    composable(Destination.BOM.route) { BomScreen(viewModels.bom) }
                    composable(Destination.BUDGET.route) { BudgetScreen(viewModels.budget) }
                    composable(Destination.ADMIN_DATA.route) {
                        AdminDataScreen(viewModels.adminData)
                    }
                    composable(Destination.ADMIN_LOGS.route) {
                        AdminLogsScreen(viewModels.adminLogs)
                    }
                    composable(Destination.ADMIN_VERSION.route) {
                        AdminVersionScreen(viewModels.adminVersion)
                    }
                }
            }
        }
    }
}

@Composable
private fun WrongRoleScreen(role: String, onLogout: () -> Unit) {
    Column(modifier = Modifier.padding(SpacingLarge)) {
        Text(
            "This app is for admin accounts only. Signed-in role: $role",
            style = MaterialTheme.typography.bodyLarge,
        )
        Button(
            onClick = onLogout,
            modifier = Modifier
                .padding(top = SpacingMedium)
                .semantics { contentDescription = "log out" },
        ) {
            Text("Log out")
        }
    }
}
