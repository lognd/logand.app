package app.logand.mobile.ui.admin.bom

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.AddMaterialLineRequest
import app.logand.core.model.BomCostBreakdown
import app.logand.core.model.BomSummary
import app.logand.core.model.ConsumeBomRequest
import app.logand.core.model.CreateBomRequest
import app.logand.core.model.InventoryItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val LOG_TAG = "BomViewModel"

// Mirrors CreateBomForm.tsx's field set exactly (labor hours/rate/
// overhead all default to "0" as strings, same as the backend request).
data class BomCreateFormState(
    val name: String = "",
    val laborHours: String = "0",
    val laborRate: String = "0",
    val overheadPercent: String = "0",
)

data class BomUiState(
    val boms: List<BomSummary> = emptyList(),
    val inventoryItems: List<InventoryItem> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val createForm: BomCreateFormState = BomCreateFormState(),
    // Cost breakdowns are per-BOM and per-build-quantity, matching
    // BomDetail.tsx's own query keyed by (bom.id, buildQuantity) -- kept
    // as the last-fetched breakdown per BOM id rather than a full cache,
    // since only one BOM's detail is ever expanded at a time in the UI.
    val costBreakdownsByBomId: Map<String, BomCostBreakdown> = emptyMap(),
    val selectedBomId: String? = null,
)

// Drives the admin Bill of Materials screen: list/create/delete BOMs,
// add/remove material lines, preview a cost breakdown for a given build
// quantity, and record a "consume stock" build -- same feature set as
// Bom.tsx's AdminBom + BomDetail.
class BomViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(BomUiState())
    val uiState: StateFlow<BomUiState> = _uiState.asStateFlow()

    fun load() {
        logger?.debug(LOG_TAG, "loading BOM list")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listBoms()) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "loaded ${result.data.size} BOMs")
                    _uiState.update { it.copy(boms = result.data, isLoading = false) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "load failed: ${result.message}")
                    _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "load network error")
                    _uiState.update { it.copy(
                        isLoading = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Selecting a BOM lazily loads the inventory-item picker list (for
    // "add material line") -- mirrors BomDetail.tsx's own itemsQuery,
    // which only runs once a BOM is expanded.
    fun selectBom(bomId: String?) {
        logger?.debug(LOG_TAG, "selecting bom=$bomId")
        _uiState.update { it.copy(selectedBomId = bomId) }
        if (bomId == null) return
        viewModelScope.launch {
            when (val result = apiClient().admin.searchInventoryItems()) {
                is ApiResult.Success -> _uiState.update { it.copy(inventoryItems = result.data) }
                is ApiResult.HttpError -> _uiState.update { it.copy(errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
        loadCostBreakdown(bomId, buildQuantity = 1)
    }

    fun updateCreateForm(transform: (BomCreateFormState) -> BomCreateFormState) {
        _uiState.update { it.copy(createForm = transform(it.createForm)) }
    }

    fun createBom() {
        val form = _uiState.value.createForm
        if (form.name.isBlank()) {
            logger?.warn(LOG_TAG, "createBom rejected: blank name")
            _uiState.update { it.copy(errorMessage = "Name is required.") }
            return
        }
        logger?.info(LOG_TAG, "creating BOM name=${form.name}")
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.createBom(
                CreateBomRequest(
                    name = form.name.trim(),
                    labor_hours = form.laborHours.trim().ifBlank { "0" },
                    labor_rate = form.laborRate.trim().ifBlank { "0" },
                    overhead_percent = form.overheadPercent.trim().ifBlank { "0" },
                ),
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "BOM created id=${result.data.id}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        createForm = BomCreateFormState(),
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "createBom failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "createBom network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun deleteBom(bomId: String) {
        logger?.info(LOG_TAG, "deleting BOM=$bomId")
        viewModelScope.launch {
            when (val result = apiClient().admin.deleteBom(bomId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(selectedBomId = null) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "deleteBom failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "deleteBom network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun addMaterialLine(bomId: String, itemId: String, quantityPerUnit: Int) {
        logger?.info(LOG_TAG, "adding material line bom=$bomId item=$itemId qty=$quantityPerUnit")
        viewModelScope.launch {
            val result = apiClient().admin.addBomMaterialLine(
                bomId,
                AddMaterialLineRequest(item_id = itemId, quantity_per_unit = quantityPerUnit),
            )
            when (result) {
                is ApiResult.Success -> loadCostBreakdown(bomId, buildQuantity = 1)
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "addMaterialLine failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "addMaterialLine network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun removeMaterialLine(bomId: String, itemId: String) {
        logger?.info(LOG_TAG, "removing material line bom=$bomId item=$itemId")
        viewModelScope.launch {
            when (val result = apiClient().admin.removeBomMaterialLine(bomId, itemId)) {
                is ApiResult.Success -> loadCostBreakdown(bomId, buildQuantity = 1)
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "removeMaterialLine failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "removeMaterialLine network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun loadCostBreakdown(bomId: String, buildQuantity: Int) {
        val safeQuantity = maxOf(1, buildQuantity)
        logger?.debug(LOG_TAG, "loading cost breakdown bom=$bomId qty=$safeQuantity")
        viewModelScope.launch {
            when (val result = apiClient().admin.getBomCostBreakdown(bomId, safeQuantity)) {
                is ApiResult.Success -> _uiState.update { it.copy(
                    costBreakdownsByBomId = it.costBreakdownsByBomId + (bomId to result.data),
                ) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "loadCostBreakdown failed: ${result.message}")
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "loadCostBreakdown network error: ${result.cause}")
                    _uiState.update { it.copy(
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Deducts stock for [buildQuantity] builds across every material
    // line -- irreversible except by a new adjustment with the reverse
    // delta, same as ConsumeBomControl's confirm text in Bom.tsx.
    fun consumeBom(bomId: String, buildQuantity: Int, reason: String?, onDone: (Boolean) -> Unit = {}) {
        val safeQuantity = maxOf(1, buildQuantity)
        logger?.info(LOG_TAG, "consuming bom=$bomId qty=$safeQuantity reason=$reason")
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.consumeBom(
                bomId,
                ConsumeBomRequest(build_quantity = safeQuantity, reason = reason?.ifBlank { null }),
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "consume recorded adjustments=${result.data.adjustment_ids}")
                    _uiState.update { it.copy(isSubmitting = false) }
                    loadCostBreakdown(bomId, safeQuantity)
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "consumeBom failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "consumeBom network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }
}
