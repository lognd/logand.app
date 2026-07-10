package app.logand.mobile.ui.admin.inventory

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.InventoryAdjustment
import app.logand.core.model.InventoryItem
import app.logand.core.model.InventoryLocation
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val LOG_TAG = "InventoryViewModel"

// Mirrors AdminInventory.tsx's create-item form -- name/quantity/location
// are the only fields the web form actually collects (description/tags
// are left null/empty there too, see frontend's onSubmit).
data class InventoryCreateFormState(
    val name: String = "",
    val quantity: String = "1",
    val locationId: String = "",
)

data class InventoryUiState(
    val items: List<InventoryItem> = emptyList(),
    val locations: List<InventoryLocation> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val createForm: InventoryCreateFormState = InventoryCreateFormState(),
    // Per-item adjustment history, keyed by item id -- only populated once
    // a caller actually asks for it (loadAdjustments), matching
    // AdjustQuantityControl's own "History" toggle in the web app, which
    // only fires its query when the history panel is shown.
    val adjustmentsByItemId: Map<String, List<InventoryAdjustment>> = emptyMap(),
)

// Drives the admin Inventory screen: list items + locations, create an
// item, adjust an item's quantity (with a before/after diff resolved by
// the caller before calling adjustQuantity -- see InventoryScreen's
// AdjustQuantityDialog for that confirm-before-commit UX, matching
// AdjustQuantityControl.tsx's inline two-step confirm), view adjustment
// history, set unit cost, and delete an item.
class InventoryViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(InventoryUiState())
    val uiState: StateFlow<InventoryUiState> = _uiState.asStateFlow()

    fun load() {
        logger?.debug(LOG_TAG, "loading inventory items and locations")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val itemsResult = apiClient().admin.searchInventoryItems()) {
                is ApiResult.Success -> {
                    when (val locationsResult = apiClient().admin.listInventoryLocations()) {
                        is ApiResult.Success -> {
                            logger?.info(
                                LOG_TAG,
                                "loaded ${itemsResult.data.size} items, " +
                                    "${locationsResult.data.size} locations",
                            )
                            _uiState.update { it.copy(
                                items = itemsResult.data,
                                locations = locationsResult.data,
                                isLoading = false,
                            ) }
                        }
                        is ApiResult.HttpError -> fail(locationsResult.message)
                        is ApiResult.NetworkError -> failNetwork()
                    }
                }
                is ApiResult.HttpError -> fail(itemsResult.message)
                is ApiResult.NetworkError -> failNetwork()
            }
        }
    }

    fun updateCreateForm(transform: (InventoryCreateFormState) -> InventoryCreateFormState) {
        _uiState.update { it.copy(createForm = transform(it.createForm)) }
    }

    fun createItem() {
        val form = _uiState.value.createForm
        val quantity = form.quantity.trim().toIntOrNull()
        if (form.name.isBlank() || form.locationId.isBlank() || quantity == null) {
            logger?.warn(LOG_TAG, "createItem rejected: name/location/quantity invalid")
            _uiState.update { it.copy(
                errorMessage = "Name, location, and a valid quantity are required.",
            ) }
            return
        }
        logger?.info(LOG_TAG, "creating item name=${form.name} location=${form.locationId}")
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.createInventoryItem(
                name = form.name.trim(),
                locationId = form.locationId.trim(),
                quantity = quantity,
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "item created id=${result.data.id}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        createForm = InventoryCreateFormState(),
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "createItem failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "createItem network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // [delta]/[reason] are expected to already be validated (non-zero
    // delta, non-blank reason, projected quantity >= 0) by the caller --
    // see InventoryScreen's AdjustQuantityDialog, which computes and shows
    // the before/after diff itself before this is ever invoked, mirroring
    // AdjustQuantityControl.tsx's client-side "would go negative" guard.
    fun adjustQuantity(itemId: String, delta: Int, reason: String) {
        logger?.info(LOG_TAG, "adjusting item=$itemId delta=$delta reason=$reason")
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.adjustInventoryQuantity(itemId, delta, reason)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "adjustment recorded id=${result.data.id}")
                    _uiState.update { it.copy(isSubmitting = false) }
                    load()
                    loadAdjustments(itemId)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "adjustQuantity failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "adjustQuantity network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun loadAdjustments(itemId: String) {
        logger?.debug(LOG_TAG, "loading adjustment history for item=$itemId")
        viewModelScope.launch {
            when (val result = apiClient().admin.listInventoryAdjustments(itemId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        adjustmentsByItemId = it.adjustmentsByItemId +
                            (itemId to result.data),
                    ) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "loadAdjustments failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "loadAdjustments network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Matches UnitCostControl.tsx -- the only way to populate what a
    // BOM's cost breakdown requires of every material line's item.
    fun setUnitCost(itemId: String, unitCost: String) {
        logger?.info(LOG_TAG, "setting unit cost item=$itemId cost=$unitCost")
        viewModelScope.launch {
            when (val result = apiClient().admin.updateInventoryItemUnitCost(itemId, unitCost)) {
                is ApiResult.Success -> load()
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "setUnitCost failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "setUnitCost network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun deleteItem(itemId: String) {
        logger?.info(LOG_TAG, "deleting item=$itemId")
        viewModelScope.launch {
            when (val result = apiClient().admin.deleteInventoryItem(itemId)) {
                is ApiResult.Success -> load()
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "deleteItem failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "deleteItem network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    private fun fail(message: String) {
        logger?.warn(LOG_TAG, "load failed: $message")
        _uiState.update { it.copy(isLoading = false, errorMessage = message) }
    }

    private fun failNetwork() {
        logger?.warn(LOG_TAG, "load network error")
        _uiState.update { it.copy(
            isLoading = false,
            errorMessage = "Could not reach the server. Check your connection.",
        ) }
    }
}
