package app.logand.mobile.ui.mileage

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.model.MileageEntry
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

// Whether the "distance" or "odometer" input mode is active -- mirrors
// domain/mileage/service.py::_resolve_distance's "either/or, never both"
// rule at the UI layer: only one set of fields is ever shown/submitted
// at a time, so a user can't accidentally fill in both and have the
// server silently prefer one.
enum class DistanceInputMode { RAW_DISTANCE, ODOMETER_READINGS }

data class MileageFormState(
    val vehicle: String = "",
    val occurredOn: String = "",
    val inputMode: DistanceInputMode = DistanceInputMode.RAW_DISTANCE,
    val distance: String = "",
    val startOdometer: String = "",
    val endOdometer: String = "",
    val purpose: String = "",
    val business: Boolean = true,
    val memo: String = "",
)

data class MileageUiState(
    val entries: List<MileageEntry> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val form: MileageFormState = MileageFormState(),
)

class MileageViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(MileageUiState())
    val uiState: StateFlow<MileageUiState> = _uiState.asStateFlow()

    fun load() {
        _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
        viewModelScope.launch {
            when (val result = apiClient().listMileage()) {
                is ApiResult.Success -> _uiState.value =
                    _uiState.value.copy(entries = result.data, isLoading = false)
                is ApiResult.HttpError -> _uiState.value =
                    _uiState.value.copy(isLoading = false, errorMessage = result.message)
                is ApiResult.NetworkError -> _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                )
            }
        }
    }

    fun updateForm(transform: (MileageFormState) -> MileageFormState) {
        _uiState.value = _uiState.value.copy(form = transform(_uiState.value.form))
    }

    fun submit() {
        val form = _uiState.value.form
        if (form.vehicle.isBlank() || form.occurredOn.isBlank()) {
            _uiState.value = _uiState.value.copy(
                errorMessage = "Vehicle and date are required.",
            )
            return
        }
        _uiState.value = _uiState.value.copy(isSubmitting = true, errorMessage = null)
        viewModelScope.launch {
            val result = apiClient().createMileageEntry(
                vehicle = form.vehicle.trim(),
                occurredOn = form.occurredOn.trim(),
                distance = if (form.inputMode == DistanceInputMode.RAW_DISTANCE) {
                    form.distance.trim().ifBlank { null }
                } else {
                    null
                },
                startOdometer = if (form.inputMode == DistanceInputMode.ODOMETER_READINGS) {
                    form.startOdometer.trim().ifBlank { null }
                } else {
                    null
                },
                endOdometer = if (form.inputMode == DistanceInputMode.ODOMETER_READINGS) {
                    form.endOdometer.trim().ifBlank { null }
                } else {
                    null
                },
                purpose = form.purpose.trim().ifBlank { null },
                business = form.business,
                memo = form.memo.trim().ifBlank { null },
            )
            when (result) {
                is ApiResult.Success -> {
                    _uiState.value = _uiState.value.copy(
                        isSubmitting = false,
                        form = MileageFormState(),
                    )
                    load()
                }
                is ApiResult.HttpError -> _uiState.value =
                    _uiState.value.copy(isSubmitting = false, errorMessage = result.message)
                is ApiResult.NetworkError -> _uiState.value = _uiState.value.copy(
                    isSubmitting = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                )
            }
        }
    }

    fun delete(id: String) {
        viewModelScope.launch {
            when (val result = apiClient().deleteMileageEntry(id)) {
                is ApiResult.Success -> load()
                is ApiResult.HttpError -> _uiState.value =
                    _uiState.value.copy(errorMessage = result.message)
                is ApiResult.NetworkError -> _uiState.value = _uiState.value.copy(
                    errorMessage = "Could not reach the server. Check your connection.",
                )
            }
        }
    }
}
