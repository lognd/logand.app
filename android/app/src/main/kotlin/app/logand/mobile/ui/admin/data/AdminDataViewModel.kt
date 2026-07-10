package app.logand.mobile.ui.admin.data

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.AdminAuditLogEntry
import app.logand.core.model.AdminTableRow
import app.logand.core.model.TableColumn
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

private const val LOG_TAG = "AdminDataViewModel"
private const val ROWS_PAGE_SIZE = 50
private const val CHANGES_PAGE_SIZE = 50

// Renders one JsonElement value for display/editing -- mirrors the web
// app's AdminData.tsx::formatValue exactly (null -> "(null)", objects/
// arrays -> raw JSON text, everything else -> its plain content) since
// admin table rows have no fixed Kotlin shape (see AdminTableRow's own
// doc comment in Admin.kt).
fun formatAdminValue(value: JsonElement?): String {
    if (value == null || value is JsonNull) return "(null)"
    return when (value) {
        is JsonPrimitive -> value.content
        else -> value.toString()
    }
}

// The row's own "id" column, read as plain text -- every admin table row
// exposes an "id" key (see api/admin_data.py), so this never falls back
// to guessing a different key.
fun AdminTableRow.rowId(): String = formatAdminValue(this["id"])

data class AdminDataUiState(
    val tables: List<String> = emptyList(),
    val isLoadingTables: Boolean = false,
    val selectedTable: String? = null,

    val schema: List<TableColumn> = emptyList(),
    val isLoadingSchema: Boolean = false,

    val rows: List<AdminTableRow> = emptyList(),
    val rowsOffset: Int = 0,
    val isLoadingRows: Boolean = false,
    val hasMoreRows: Boolean = false,

    val selectedRowId: String? = null,
    val selectedRow: AdminTableRow? = null,
    val isLoadingRow: Boolean = false,
    // Column name -> pending text edit, only for columns the user has
    // actually touched -- unedited columns keep showing the live row
    // value (see AdminData.tsx's identical edits map).
    val edits: Map<String, String> = emptyMap(),
    val confirmingUpdate: Boolean = false,
    val isSubmittingUpdate: Boolean = false,
    val confirmingDelete: Boolean = false,
    val isSubmittingDelete: Boolean = false,

    val insertDialogOpen: Boolean = false,
    val insertValues: Map<String, String> = emptyMap(),
    val isSubmittingInsert: Boolean = false,

    val showChangeLog: Boolean = false,
    val changes: List<AdminAuditLogEntry> = emptyList(),
    val changesOffset: Int = 0,
    val isLoadingChanges: Boolean = false,
    val hasMoreChanges: Boolean = false,
    // Revert requires an explicit confirm step -- never a single tap
    // (destructive: it writes the table back to a prior state).
    val confirmingRevertId: String? = null,
    val isSubmittingRevert: Boolean = false,

    val errorMessage: String? = null,
) {
    // Only the columns whose pending edit actually differs from the
    // live row value -- what gets sent to updateRow, and what the
    // confirm-change review list shows (mirrors AdminData.tsx's
    // changedKeys).
    val changedKeys: List<String>
        get() {
            val row = selectedRow ?: return emptyList()
            return edits.keys.filter { key -> edits[key] != formatAdminValue(row[key]) }
        }
}

// Generic table browser/editor -- the one screen with "absolute power,
// but never a corrupt state" over every real backend table (see
// api/admin_data.py). Rows are schemaless JsonObjects (AdminTableRow),
// so this ViewModel never assumes a fixed set of columns; it renders
// whatever TableColumn list the backend reports for the selected table.
// Every write (update/delete/revert) is mirrored into the change log via
// AdminApi.listChanges/revertChange, exactly like the web app's
// AdminData.tsx, so a mistake here is always recoverable.
class AdminDataViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AdminDataUiState())
    val uiState: StateFlow<AdminDataUiState> = _uiState.asStateFlow()

    fun loadTables() {
        logger?.info(LOG_TAG, "loading table list")
        _uiState.update { it.copy(isLoadingTables = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listTables()) {
                is ApiResult.Success -> _uiState.update { it.copy(tables = result.data, isLoadingTables = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "listTables failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingTables = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "listTables network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isLoadingTables = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Selecting a table resets every row/selection/paging state that
    // belonged to the previous table -- otherwise a stale selectedRowId
    // from table A could be reused as if it were a row of table B.
    //
    // loadSchema and loadRows below run as two independent coroutines
    // that each finish by mutating _uiState on their own schedule. Every
    // write here and in those two functions MUST go through
    // _uiState.update{} (atomic compare-and-swap), never
    // `_uiState.value = _uiState.value.copy(...)` -- the latter is a
    // non-atomic read-modify-write, so whichever coroutine finishes
    // second would silently clobber the first one's fields (e.g.
    // isLoadingRows/isLoadingSchema stuck true forever).
    fun selectTable(tableName: String?) {
        logger?.info(LOG_TAG, "selecting table: $tableName")
        _uiState.update { it.copy(
            selectedTable = tableName,
            schema = emptyList(),
            rows = emptyList(),
            rowsOffset = 0,
            hasMoreRows = false,
            selectedRowId = null,
            selectedRow = null,
            edits = emptyMap(),
            confirmingUpdate = false,
            confirmingDelete = false,
            insertDialogOpen = false,
            insertValues = emptyMap(),
            errorMessage = null,
        ) }
        if (tableName != null) {
            loadSchema(tableName)
            loadRows(offset = 0)
        }
    }

    private fun loadSchema(tableName: String) {
        _uiState.update { it.copy(isLoadingSchema = true) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getTableSchema(tableName)) {
                is ApiResult.Success -> _uiState.update { it.copy(schema = result.data, isLoadingSchema = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "getTableSchema($tableName) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingSchema = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingSchema = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun loadRows(offset: Int = 0) {
        val tableName = _uiState.value.selectedTable ?: return
        _uiState.update { it.copy(isLoadingRows = true, errorMessage = null) }
        viewModelScope.launch {
            when (
                val result = apiClient().admin.listRows(
                    tableName = tableName,
                    limit = ROWS_PAGE_SIZE,
                    offset = offset,
                )
            ) {
                is ApiResult.Success -> _uiState.update { it.copy(
                    rows = result.data,
                    rowsOffset = offset,
                    hasMoreRows = result.data.size == ROWS_PAGE_SIZE,
                    isLoadingRows = false,
                ) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "listRows($tableName) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingRows = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingRows = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun nextRowsPage() {
        if (_uiState.value.hasMoreRows) loadRows(offset = _uiState.value.rowsOffset + ROWS_PAGE_SIZE)
    }

    fun previousRowsPage() {
        val newOffset = (_uiState.value.rowsOffset - ROWS_PAGE_SIZE).coerceAtLeast(0)
        loadRows(offset = newOffset)
    }

    fun selectRow(rowId: String?) {
        logger?.info(LOG_TAG, "selecting row: $rowId")
        _uiState.update { it.copy(
            selectedRowId = rowId,
            selectedRow = null,
            edits = emptyMap(),
            confirmingUpdate = false,
            confirmingDelete = false,
        ) }
        if (rowId != null) loadRow(rowId)
    }

    private fun loadRow(rowId: String) {
        val tableName = _uiState.value.selectedTable ?: return
        _uiState.update { it.copy(isLoadingRow = true) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getRow(tableName, rowId)) {
                is ApiResult.Success -> _uiState.update { it.copy(selectedRow = result.data, isLoadingRow = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "getRow($tableName, $rowId) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingRow = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingRow = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun updateEditField(column: String, value: String) {
        _uiState.update { it.copy(
            edits = it.edits + (column to value),
        ) }
    }

    // Step 1 of 2 for a row update -- shows the before/after diff, does
    // NOT write anything yet (see submitUpdate). Never a one-tap write.
    fun requestConfirmUpdate() {
        if (_uiState.value.changedKeys.isEmpty()) return
        _uiState.update { it.copy(confirmingUpdate = true) }
    }

    fun cancelConfirmUpdate() {
        _uiState.update { it.copy(confirmingUpdate = false) }
    }

    fun submitUpdate() {
        if (!_uiState.value.confirmingUpdate) return
        val tableName = _uiState.value.selectedTable ?: return
        val rowId = _uiState.value.selectedRowId ?: return
        val changedKeys = _uiState.value.changedKeys
        if (changedKeys.isEmpty()) return
        val edits = _uiState.value.edits
        val changes = buildJsonObject {
            changedKeys.forEach { key -> put(key, JsonPrimitive(edits.getValue(key))) }
        }
        logger?.info(LOG_TAG, "submitting update on $tableName/$rowId: $changedKeys")
        _uiState.update { it.copy(isSubmittingUpdate = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.updateRow(tableName, rowId, changes)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        isSubmittingUpdate = false,
                        confirmingUpdate = false,
                        edits = emptyMap(),
                    ) }
                    loadRow(rowId)
                    loadRows(offset = _uiState.value.rowsOffset)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "updateRow($tableName, $rowId) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingUpdate = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isSubmittingUpdate = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    // Step 1 of 2 for a row delete -- destructive, so this only arms the
    // confirmation UI; submitDelete does the actual write.
    fun requestConfirmDelete() {
        _uiState.update { it.copy(confirmingDelete = true) }
    }

    fun cancelConfirmDelete() {
        _uiState.update { it.copy(confirmingDelete = false) }
    }

    fun submitDelete() {
        if (!_uiState.value.confirmingDelete) return
        val tableName = _uiState.value.selectedTable ?: return
        val rowId = _uiState.value.selectedRowId ?: return
        logger?.info(LOG_TAG, "submitting delete on $tableName/$rowId")
        _uiState.update { it.copy(isSubmittingDelete = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.deleteRow(tableName, rowId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        isSubmittingDelete = false,
                        confirmingDelete = false,
                        selectedRowId = null,
                        selectedRow = null,
                    ) }
                    loadRows(offset = _uiState.value.rowsOffset)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "deleteRow($tableName, $rowId) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingDelete = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isSubmittingDelete = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun openInsertDialog() {
        _uiState.update { it.copy(insertDialogOpen = true, insertValues = emptyMap()) }
    }

    fun closeInsertDialog() {
        _uiState.update { it.copy(insertDialogOpen = false, insertValues = emptyMap()) }
    }

    fun updateInsertField(column: String, value: String) {
        _uiState.update { it.copy(
            insertValues = it.insertValues + (column to value),
        ) }
    }

    // Insert is not destructive (nothing existing is overwritten), so
    // unlike update/delete it does not require a separate confirm step
    // -- it still lands in the change log and can be reverted like any
    // other write.
    fun submitInsert() {
        val tableName = _uiState.value.selectedTable ?: return
        val values = buildJsonObject {
            _uiState.value.insertValues.forEach { (key, value) -> put(key, JsonPrimitive(value)) }
        }
        logger?.info(LOG_TAG, "submitting insert on $tableName: ${_uiState.value.insertValues.keys}")
        _uiState.update { it.copy(isSubmittingInsert = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.insertRow(tableName, values)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        isSubmittingInsert = false,
                        insertDialogOpen = false,
                        insertValues = emptyMap(),
                    ) }
                    loadRows(offset = _uiState.value.rowsOffset)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "insertRow($tableName) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingInsert = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isSubmittingInsert = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun toggleChangeLog() {
        val next = !_uiState.value.showChangeLog
        _uiState.update { it.copy(showChangeLog = next) }
        if (next && _uiState.value.changes.isEmpty()) loadChanges(offset = 0)
    }

    fun loadChanges(offset: Int = 0) {
        _uiState.update { it.copy(isLoadingChanges = true, errorMessage = null) }
        viewModelScope.launch {
            when (
                val result = apiClient().admin.listChanges(limit = CHANGES_PAGE_SIZE, offset = offset)
            ) {
                is ApiResult.Success -> _uiState.update { it.copy(
                    changes = result.data,
                    changesOffset = offset,
                    hasMoreChanges = result.data.size == CHANGES_PAGE_SIZE,
                    isLoadingChanges = false,
                ) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "listChanges failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingChanges = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingChanges = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun nextChangesPage() {
        if (_uiState.value.hasMoreChanges) loadChanges(offset = _uiState.value.changesOffset + CHANGES_PAGE_SIZE)
    }

    fun previousChangesPage() {
        val newOffset = (_uiState.value.changesOffset - CHANGES_PAGE_SIZE).coerceAtLeast(0)
        loadChanges(offset = newOffset)
    }

    // Step 1 of 2 for a revert -- destructive (overwrites current state
    // with a prior one), so this only arms the confirmation UI.
    fun requestRevert(logId: String) {
        _uiState.update { it.copy(confirmingRevertId = logId) }
    }

    fun cancelRevert() {
        _uiState.update { it.copy(confirmingRevertId = null) }
    }

    fun submitRevert(logId: String) {
        if (_uiState.value.confirmingRevertId != logId) return
        logger?.info(LOG_TAG, "submitting revert of change $logId")
        _uiState.update { it.copy(isSubmittingRevert = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.revertChange(logId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        isSubmittingRevert = false,
                        confirmingRevertId = null,
                    ) }
                    loadChanges(offset = _uiState.value.changesOffset)
                    _uiState.value.selectedTable?.let { loadRows(offset = _uiState.value.rowsOffset) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "revertChange($logId) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingRevert = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isSubmittingRevert = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }
}
