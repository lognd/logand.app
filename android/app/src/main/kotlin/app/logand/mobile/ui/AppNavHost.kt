package app.logand.mobile.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
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
import app.logand.mobile.ui.login.LoginScreen
import app.logand.mobile.ui.login.LoginViewModel
import app.logand.mobile.ui.mileage.MileageScreen
import app.logand.mobile.ui.mileage.MileageViewModel
import app.logand.mobile.ui.receipts.ReceiptsScreen
import app.logand.mobile.ui.receipts.ReceiptsViewModel

private enum class Tab(val route: String, val label: String) {
    MILEAGE("mileage", "Mileage"),
    RECEIPTS("receipts", "Receipts"),
}

@Composable
fun AppNavHost(
    loginViewModel: LoginViewModel,
    mileageViewModel: MileageViewModel,
    receiptsViewModel: ReceiptsViewModel,
) {
    val session by loginViewModel.session.collectAsStateWithLifecycle()

    when (val current = session) {
        is SessionState.LoggedOut -> LoginScreen(loginViewModel)
        is SessionState.LoggedInWrongRole -> WrongRoleScreen(
            role = current.me.role,
            onLogout = loginViewModel::logout,
        )
        is SessionState.LoggedIn -> MainTabs(
            onLogout = loginViewModel::logout,
            mileageViewModel = mileageViewModel,
            receiptsViewModel = receiptsViewModel,
        )
    }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun MainTabs(
    onLogout: () -> Unit,
    mileageViewModel: MileageViewModel,
    receiptsViewModel: ReceiptsViewModel,
) {
    val navController = rememberNavController()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("logand.app") },
                actions = {
                    androidx.compose.material3.TextButton(
                        onClick = onLogout,
                        modifier = Modifier.semantics { contentDescription = "log out" },
                    ) { Text("Log out") }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
            )
        },
        bottomBar = {
            val backStackEntry by navController.currentBackStackEntryAsState()
            val currentDestination = backStackEntry?.destination
            NavigationBar {
                Tab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = currentDestination?.hierarchy?.any { it.route == tab.route } == true,
                        onClick = {
                            navController.navigate(tab.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = {
                            Icon(
                                if (tab == Tab.MILEAGE) Icons.AutoMirrored.Filled.List else Icons.Default.Receipt,
                                contentDescription = tab.label,
                            )
                        },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Tab.MILEAGE.route,
            modifier = Modifier.padding(padding),
        ) {
            composable(Tab.MILEAGE.route) { MileageScreen(mileageViewModel) }
            composable(Tab.RECEIPTS.route) { ReceiptsScreen(receiptsViewModel) }
        }
    }
}

@Composable
private fun WrongRoleScreen(role: String, onLogout: () -> Unit) {
    androidx.compose.foundation.layout.Column(
        modifier = Modifier.padding(app.logand.mobile.ui.theme.SpacingLarge),
    ) {
        Text(
            "This app is for admin accounts only. Signed-in role: $role",
            style = MaterialTheme.typography.bodyLarge,
        )
        androidx.compose.material3.Button(
            onClick = onLogout,
            modifier = Modifier
                .padding(top = app.logand.mobile.ui.theme.SpacingMedium)
                .semantics { contentDescription = "log out" },
        ) {
            Text("Log out")
        }
    }
}
