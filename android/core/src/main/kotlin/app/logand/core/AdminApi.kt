package app.logand.core

import app.logand.core.model.AddMaterialLineRequest
import app.logand.core.model.AdjustQuantityRequest
import app.logand.core.model.AdjustmentIds
import app.logand.core.model.AdminAuditLogEntry
import app.logand.core.model.AdminTableRow
import app.logand.core.model.BomCostBreakdown
import app.logand.core.model.BomSummary
import app.logand.core.model.BudgetEntry
import app.logand.core.model.ChangeId
import app.logand.core.model.ConsumeBomRequest
import app.logand.core.model.CreateBomRequest
import app.logand.core.model.CreatedId
import app.logand.core.model.CustomerAddressRequest
import app.logand.core.model.CustomerDetail
import app.logand.core.model.CustomerListItem
import app.logand.core.model.InsertRowRequest
import app.logand.core.model.InventoryAdjustment
import app.logand.core.model.InventoryItem
import app.logand.core.model.InventoryLocation
import app.logand.core.model.InvoiceDetail
import app.logand.core.model.InvoiceLineItem
import app.logand.core.model.InvoiceStats
import app.logand.core.model.InvoiceSummary
import app.logand.core.model.LogFileInfo
import app.logand.core.model.ManualPaymentRequest
import app.logand.core.model.PaymentProofSummary
import app.logand.core.model.RefundRequest
import app.logand.core.model.StripeTaxReconcile
import app.logand.core.model.TableColumn
import app.logand.core.model.TaxClassification
import app.logand.core.model.TaxClassificationOverrideRequest
import app.logand.core.model.TaxReport
import app.logand.core.model.TaxRule
import app.logand.core.model.TaxRuleCreateRequest
import app.logand.core.model.UpdateRowRequest
import app.logand.core.model.VersionInfo
import app.logand.core.model.ResetPasswordRequest
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

private val JSON_MEDIA_TYPE = "application/json".toMediaType()

// The full admin-parity surface (invoices, customers, inventory, BOM,
// budget, raw-data browser, logs, version) -- gives the Android app the
// same admin capability the web app has. Kept as its own class rather
// than folding into ApiClient so that class doesn't grow unboundedly;
// shares ApiClient's exact request/CSRF/error/401 plumbing via the same
// HttpPlumbing instance (see HttpPlumbing's own doc comment), so every
// method here behaves identically to ApiClient's own methods -- same
// ApiResult error shape, same CSRF header handling, same onUnauthorized
// firing on 401, same withContext(Dispatchers.IO) dispatch (all inside
// HttpPlumbing.request).
//
// Every request/response shape below is copy-derived from the real
// backend route signatures (never guessed) -- see api/invoices.py,
// api/admin_users.py, api/inventory.py, api/bom.py, api/budget.py,
// api/admin_data.py, api/admin_logs.py, api/admin_version.py, api/tax.py.
class AdminApi internal constructor(private val plumbing: HttpPlumbing) {

    // -- invoices ----------------------------------------------------------

    suspend fun listInvoices(
        status: String? = null,
        customerId: String? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<InvoiceSummary>> = with(plumbing) {
        val url = urlBuilder("/api/admin/invoices").apply {
            status?.let { addQueryParameter("status", it) }
            customerId?.let { addQueryParameter("customer_id", it) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(InvoiceSummary.serializer()))
    }

    suspend fun getInvoiceStats(): ApiResult<InvoiceStats> = with(plumbing) {
        request(method = "GET", path = "/api/admin/invoices/stats").decode(InvoiceStats.serializer())
    }

    suspend fun getInvoice(invoiceId: String): ApiResult<InvoiceDetail> = with(plumbing) {
        request(method = "GET", path = "/api/admin/invoices/$invoiceId").decode(InvoiceDetail.serializer())
    }

    // Exactly one of customerId/customerEmail is expected by the backend
    // -- customerId for an existing customer account, customerEmail as
    // the get-or-create-a-contact-user alternative (see
    // docs/design/17-contact-users-and-email-verification.md). Both are
    // nullable here rather than this method taking a sealed choice type
    // so callers can pass whichever one the UI's create-invoice form
    // collected, unchanged from what the backend route itself accepts.
    suspend fun createInvoice(
        customerId: String? = null,
        customerEmail: String? = null,
        lineItems: List<InvoiceLineItem>,
        memo: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/invoices").apply {
            customerId?.let { addQueryParameter("customer_id", it) }
            customerEmail?.let { addQueryParameter("customer_email", it) }
            memo?.let { addQueryParameter("memo", it) }
        }.build()
        val body = json.encodeToString(ListSerializer(InvoiceLineItem.serializer()), lineItems)
            .toRequestBody(JSON_MEDIA_TYPE)
        request(method = "POST", url = url, body = body).decode(CreatedId.serializer())
    }

    // `acknowledgeReview` is the admin's explicit, informed override of the
    // backend's "tax needs review" guard -- when true it adds
    // ?acknowledge_review=true so a flagged invoice sends anyway. Omitted
    // (false) for a normal send, which 409s (InvoiceError.NeedsReview) on a
    // flagged invoice so the admin is walked through reviewing first. See
    // api/invoices.py's send route and domain send_invoice.
    suspend fun sendInvoice(
        invoiceId: String,
        acknowledgeReview: Boolean = false,
    ): ApiResult<Unit> = with(plumbing) {
        val url = urlBuilder("/api/admin/invoices/$invoiceId/send").apply {
            if (acknowledgeReview) addQueryParameter("acknowledge_review", "true")
        }.build()
        request(method = "POST", url = url).decodeUnit()
    }

    suspend fun voidInvoice(invoiceId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "POST", path = "/api/admin/invoices/$invoiceId/void").decodeUnit()
    }

    suspend fun recordManualPayment(
        invoiceId: String,
        payment: ManualPaymentRequest,
    ): ApiResult<CreatedId> = with(plumbing) {
        val body = json.encodeToString(ManualPaymentRequest.serializer(), payment)
            .toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "POST",
            path = "/api/admin/invoices/$invoiceId/payments/manual",
            body = body,
        ).decode(CreatedId.serializer())
    }

    suspend fun refundPayment(
        invoiceId: String,
        paymentId: String,
        refund: RefundRequest,
    ): ApiResult<CreatedId> = with(plumbing) {
        val body = json.encodeToString(RefundRequest.serializer(), refund)
            .toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "POST",
            path = "/api/admin/invoices/$invoiceId/payments/$paymentId/refund",
            body = body,
        ).decode(CreatedId.serializer())
    }

    // Raw PDF bytes -- see HttpPlumbing.decodeBytes's own doc comment for
    // why binary downloads never go through the text/JSON decode path.
    suspend fun getInvoicePdf(invoiceId: String): ApiResult<ByteArray> = with(plumbing) {
        request(method = "GET", path = "/api/admin/invoices/$invoiceId/pdf").decodeBytes()
    }

    // On the invoices router (/api/admin/invoices), not the tax one --
    // matches api/invoices.py::get_tax_report exactly (declared before
    // GET /{invoice_id} on the backend so "tax-report" is never swallowed
    // as a literal invoice_id).
    suspend fun getTaxReport(
        fromDate: String,
        toDate: String,
        currency: String = "usd",
    ): ApiResult<TaxReport> = with(plumbing) {
        val url = urlBuilder("/api/admin/invoices/tax-report").apply {
            addQueryParameter("from_date", fromDate)
            addQueryParameter("to_date", toDate)
            addQueryParameter("currency", currency)
        }.build()
        request(method = "GET", url = url).decode(TaxReport.serializer())
    }

    suspend fun listPaymentProofs(invoiceId: String): ApiResult<List<PaymentProofSummary>> =
        with(plumbing) {
            request(method = "GET", path = "/api/admin/invoices/$invoiceId/payment-proof")
                .decode(ListSerializer(PaymentProofSummary.serializer()))
        }

    suspend fun downloadPaymentProof(invoiceId: String, proofId: String): ApiResult<ByteArray> =
        with(plumbing) {
            request(
                method = "GET",
                path = "/api/admin/invoices/$invoiceId/payment-proof/$proofId/file",
            ).decodeBytes()
        }

    // -- customers -----------------------------------------------------------

    suspend fun listCustomers(q: String? = null): ApiResult<List<CustomerListItem>> = with(plumbing) {
        val url = urlBuilder("/api/admin/customers").apply {
            q?.let { addQueryParameter("q", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(CustomerListItem.serializer()))
    }

    suspend fun getCustomer(userId: String): ApiResult<CustomerDetail> = with(plumbing) {
        request(method = "GET", path = "/api/admin/customers/$userId").decode(CustomerDetail.serializer())
    }

    suspend fun deactivateCustomer(userId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "POST", path = "/api/admin/customers/$userId/deactivate").decodeUnit()
    }

    suspend fun reactivateCustomer(userId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "POST", path = "/api/admin/customers/$userId/reactivate").decodeUnit()
    }

    suspend fun resetCustomerPassword(userId: String, newPassword: String): ApiResult<Unit> =
        with(plumbing) {
            val body = json.encodeToString(
                ResetPasswordRequest.serializer(),
                ResetPasswordRequest(newPassword),
            ).toRequestBody(JSON_MEDIA_TYPE)
            request(
                method = "POST",
                path = "/api/admin/customers/$userId/reset-password",
                body = body,
            ).decodeUnit()
        }

    // Replaces the customer's whole destination address (feeds the tax
    // engine's destination-jurisdiction lookup, docs/design/16-sales-tax.md
    // Phase 6) -- a null field clears it rather than leaving it as-is,
    // matching api/admin_users.py::AddressInput exactly.
    suspend fun updateCustomerAddress(
        userId: String,
        addressLine1: String? = null,
        addressCity: String? = null,
        addressState: String? = null,
        addressPostalCode: String? = null,
        addressCountry: String? = null,
    ): ApiResult<CustomerDetail> = with(plumbing) {
        val body = json.encodeToString(
            CustomerAddressRequest.serializer(),
            CustomerAddressRequest(
                address_line1 = addressLine1,
                address_city = addressCity,
                address_state = addressState,
                address_postal_code = addressPostalCode,
                address_country = addressCountry,
            ),
        ).toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "PUT",
            path = "/api/admin/customers/$userId/address",
            body = body,
        ).decode(CustomerDetail.serializer())
    }

    // -- inventory -----------------------------------------------------------

    suspend fun createInventoryLocation(
        name: String,
        description: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/inventory/locations").apply {
            addQueryParameter("name", name)
            description?.let { addQueryParameter("description", it) }
        }.build()
        request(method = "POST", url = url).decode(CreatedId.serializer())
    }

    suspend fun listInventoryLocations(): ApiResult<List<InventoryLocation>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/inventory/locations")
            .decode(ListSerializer(InventoryLocation.serializer()))
    }

    suspend fun createInventoryItem(
        name: String,
        locationId: String,
        quantity: Int = 1,
        description: String? = null,
        tags: List<String>? = null,
        unitCost: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/inventory/items").apply {
            addQueryParameter("name", name)
            addQueryParameter("location_id", locationId)
            addQueryParameter("quantity", quantity.toString())
            description?.let { addQueryParameter("description", it) }
            tags?.forEach { addQueryParameter("tags", it) }
            unitCost?.let { addQueryParameter("unit_cost", it) }
        }.build()
        request(method = "POST", url = url).decode(CreatedId.serializer())
    }

    suspend fun updateInventoryItemUnitCost(itemId: String, unitCost: String): ApiResult<Unit> =
        with(plumbing) {
            val url = urlBuilder("/api/admin/inventory/items/$itemId/unit-cost")
                .addQueryParameter("unit_cost", unitCost)
                .build()
            request(method = "PATCH", url = url).decodeUnit()
        }

    suspend fun updateInventoryItem(
        itemId: String,
        locationId: String? = null,
        quantity: Int? = null,
    ): ApiResult<Unit> = with(plumbing) {
        val url = urlBuilder("/api/admin/inventory/items/$itemId").apply {
            locationId?.let { addQueryParameter("location_id", it) }
            quantity?.let { addQueryParameter("quantity", it.toString()) }
        }.build()
        request(method = "PATCH", url = url).decodeUnit()
    }

    suspend fun adjustInventoryQuantity(
        itemId: String,
        delta: Int,
        reason: String,
    ): ApiResult<CreatedId> = with(plumbing) {
        val body = json.encodeToString(AdjustQuantityRequest.serializer(), AdjustQuantityRequest(delta, reason))
            .toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "POST",
            path = "/api/admin/inventory/items/$itemId/adjust",
            body = body,
        ).decode(CreatedId.serializer())
    }

    suspend fun listInventoryAdjustments(itemId: String): ApiResult<List<InventoryAdjustment>> =
        with(plumbing) {
            request(method = "GET", path = "/api/admin/inventory/items/$itemId/adjustments")
                .decode(ListSerializer(InventoryAdjustment.serializer()))
        }

    suspend fun searchInventoryItems(
        q: String? = null,
        locationId: String? = null,
        tag: String? = null,
    ): ApiResult<List<InventoryItem>> = with(plumbing) {
        val url = urlBuilder("/api/admin/inventory/items").apply {
            q?.let { addQueryParameter("q", it) }
            locationId?.let { addQueryParameter("location_id", it) }
            tag?.let { addQueryParameter("tag", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(InventoryItem.serializer()))
    }

    suspend fun deleteInventoryItem(itemId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "DELETE", path = "/api/admin/inventory/items/$itemId").decodeUnit()
    }

    // -- bill of materials -----------------------------------------------------

    suspend fun createBom(input: CreateBomRequest): ApiResult<CreatedId> = with(plumbing) {
        val body = json.encodeToString(CreateBomRequest.serializer(), input).toRequestBody(JSON_MEDIA_TYPE)
        request(method = "POST", path = "/api/admin/boms", body = body).decode(CreatedId.serializer())
    }

    suspend fun listBoms(): ApiResult<List<BomSummary>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/boms").decode(ListSerializer(BomSummary.serializer()))
    }

    suspend fun getBom(bomId: String): ApiResult<BomSummary> = with(plumbing) {
        request(method = "GET", path = "/api/admin/boms/$bomId").decode(BomSummary.serializer())
    }

    suspend fun deleteBom(bomId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "DELETE", path = "/api/admin/boms/$bomId").decodeUnit()
    }

    suspend fun addBomMaterialLine(
        bomId: String,
        input: AddMaterialLineRequest,
    ): ApiResult<CreatedId> = with(plumbing) {
        val body = json.encodeToString(AddMaterialLineRequest.serializer(), input).toRequestBody(JSON_MEDIA_TYPE)
        request(method = "POST", path = "/api/admin/boms/$bomId/lines", body = body).decode(CreatedId.serializer())
    }

    suspend fun removeBomMaterialLine(bomId: String, itemId: String): ApiResult<Unit> = with(plumbing) {
        request(method = "DELETE", path = "/api/admin/boms/$bomId/lines/$itemId").decodeUnit()
    }

    suspend fun getBomCostBreakdown(
        bomId: String,
        buildQuantity: Int = 1,
    ): ApiResult<BomCostBreakdown> = with(plumbing) {
        val url = urlBuilder("/api/admin/boms/$bomId/cost")
            .addQueryParameter("build_quantity", buildQuantity.toString())
            .build()
        request(method = "GET", url = url).decode(BomCostBreakdown.serializer())
    }

    suspend fun consumeBom(bomId: String, input: ConsumeBomRequest): ApiResult<AdjustmentIds> =
        with(plumbing) {
            val body = json.encodeToString(ConsumeBomRequest.serializer(), input).toRequestBody(JSON_MEDIA_TYPE)
            request(method = "POST", path = "/api/admin/boms/$bomId/consume", body = body)
                .decode(AdjustmentIds.serializer())
        }

    // -- budget --------------------------------------------------------------

    suspend fun createBudgetEntry(
        amount: String,
        category: String,
        occurredOn: String,
        vendor: String? = null,
        memo: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/budget").apply {
            addQueryParameter("amount", amount)
            addQueryParameter("category", category)
            addQueryParameter("occurred_on", occurredOn)
            vendor?.let { addQueryParameter("vendor", it) }
            memo?.let { addQueryParameter("memo", it) }
        }.build()
        request(method = "POST", url = url).decode(CreatedId.serializer())
    }

    // Evidence file must be a PDF or image (application/pdf, image/png,
    // image/jpeg) -- matches api/budget.py's own content-type check
    // (this client doesn't duplicate that validation, the backend still
    // enforces it; mimeType is just passed through as-is).
    suspend fun uploadBudgetEvidence(
        entryId: String,
        fileBytes: ByteArray,
        filename: String,
        mimeType: String,
    ): ApiResult<CreatedId> = with(plumbing) {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", filename, fileBytes.toRequestBody(mimeType.toMediaType()))
            .build()
        request(
            method = "POST",
            path = "/api/admin/budget/$entryId/evidence",
            body = body,
        ).decode(CreatedId.serializer())
    }

    suspend fun listBudgetEntries(
        category: String? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<BudgetEntry>> = with(plumbing) {
        val url = urlBuilder("/api/admin/budget").apply {
            category?.let { addQueryParameter("category", it) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(BudgetEntry.serializer()))
    }

    // Raw CSV bytes -- the accountant-handoff export, streamed by the
    // backend; decoded here as raw bytes rather than text so a caller
    // can write it straight to a file/share-sheet unmodified.
    suspend fun exportBudgetCsv(
        category: String? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<ByteArray> = with(plumbing) {
        val url = urlBuilder("/api/admin/budget/export").apply {
            category?.let { addQueryParameter("category", it) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        request(method = "GET", url = url).decodeBytes()
    }

    // -- admin data (raw table browser) --------------------------------------

    suspend fun listTables(): ApiResult<List<String>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/data/tables").decode(ListSerializer(String.serializer()))
    }

    suspend fun getTableSchema(tableName: String): ApiResult<List<TableColumn>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/data/tables/$tableName/schema")
            .decode(ListSerializer(TableColumn.serializer()))
    }

    suspend fun listRows(
        tableName: String,
        limit: Int = 50,
        offset: Int = 0,
    ): ApiResult<List<AdminTableRow>> = with(plumbing) {
        val url = urlBuilder("/api/admin/data/tables/$tableName/rows").apply {
            addQueryParameter("limit", limit.toString())
            addQueryParameter("offset", offset.toString())
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(JsonObject.serializer()))
    }

    suspend fun getRow(tableName: String, rowId: String): ApiResult<AdminTableRow> = with(plumbing) {
        request(method = "GET", path = "/api/admin/data/tables/$tableName/rows/$rowId")
            .decode(JsonObject.serializer())
    }

    suspend fun insertRow(tableName: String, values: AdminTableRow): ApiResult<ChangeId> = with(plumbing) {
        val body = json.encodeToString(InsertRowRequest.serializer(), InsertRowRequest(values))
            .toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "POST",
            path = "/api/admin/data/tables/$tableName/rows",
            body = body,
        ).decode(ChangeId.serializer())
    }

    suspend fun updateRow(
        tableName: String,
        rowId: String,
        changes: AdminTableRow,
    ): ApiResult<ChangeId> = with(plumbing) {
        val body = json.encodeToString(UpdateRowRequest.serializer(), UpdateRowRequest(changes))
            .toRequestBody(JSON_MEDIA_TYPE)
        request(
            method = "PATCH",
            path = "/api/admin/data/tables/$tableName/rows/$rowId",
            body = body,
        ).decode(ChangeId.serializer())
    }

    suspend fun deleteRow(tableName: String, rowId: String): ApiResult<ChangeId> = with(plumbing) {
        request(method = "DELETE", path = "/api/admin/data/tables/$tableName/rows/$rowId")
            .decode(ChangeId.serializer())
    }

    suspend fun listChanges(limit: Int = 50, offset: Int = 0): ApiResult<List<AdminAuditLogEntry>> =
        with(plumbing) {
            val url = urlBuilder("/api/admin/data/changes").apply {
                addQueryParameter("limit", limit.toString())
                addQueryParameter("offset", offset.toString())
            }.build()
            request(method = "GET", url = url).decode(ListSerializer(AdminAuditLogEntry.serializer()))
        }

    suspend fun revertChange(logId: String): ApiResult<ChangeId> = with(plumbing) {
        request(method = "POST", path = "/api/admin/data/changes/$logId/revert").decode(ChangeId.serializer())
    }

    // -- logs ------------------------------------------------------------------

    suspend fun listLogFiles(): ApiResult<List<LogFileInfo>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/logs/files").decode(ListSerializer(LogFileInfo.serializer()))
    }

    suspend fun tailLiveLog(lines: Int = 200): ApiResult<List<String>> = with(plumbing) {
        val url = urlBuilder("/api/admin/logs/tail").addQueryParameter("lines", lines.toString()).build()
        request(method = "GET", url = url).decode(ListSerializer(String.serializer()))
    }

    // Raw log file bytes (newline-delimited JSON) -- see
    // HttpPlumbing.decodeBytes's own doc comment.
    suspend fun downloadLogFile(name: String): ApiResult<ByteArray> = with(plumbing) {
        request(method = "GET", path = "/api/admin/logs/files/$name").decodeBytes()
    }

    // -- tax (docs/design/16-sales-tax.md) --------------------------------------

    // status=pending shows only what needs a human decision; omit for
    // every classification regardless of review state.
    suspend fun listTaxClassifications(status: String? = null): ApiResult<List<TaxClassification>> =
        with(plumbing) {
            val url = urlBuilder("/api/admin/tax/classifications").apply {
                status?.let { addQueryParameter("status", it) }
            }.build()
            request(method = "GET", url = url).decode(ListSerializer(TaxClassification.serializer()))
        }

    // `key` (the normalized item key) may contain spaces/punctuation --
    // always sent as an encoded path segment via addPathSegment, never
    // interpolated raw, so callers never have to remember to encode it
    // themselves (same concern as frontend/src/api/tax.ts's own comment).
    suspend fun confirmTaxClassification(key: String): ApiResult<TaxClassification> = with(plumbing) {
        val url = urlBuilder("/api/admin/tax/classifications")
            .addPathSegment(key)
            .addPathSegment("confirm")
            .build()
        request(method = "POST", url = url).decode(TaxClassification.serializer())
    }

    // Confirming/overriding a tax classification changes financial
    // records -- the UI must require an explicit confirm step before
    // calling this, never a single tap.
    suspend fun overrideTaxClassification(
        key: String,
        category: String,
        taxable: Boolean,
        htsCode: String? = null,
    ): ApiResult<TaxClassification> = with(plumbing) {
        val url = urlBuilder("/api/admin/tax/classifications")
            .addPathSegment(key)
            .addPathSegment("override")
            .build()
        val body = json.encodeToString(
            TaxClassificationOverrideRequest.serializer(),
            TaxClassificationOverrideRequest(category, taxable, htsCode),
        ).toRequestBody(JSON_MEDIA_TYPE)
        request(method = "POST", url = url, body = body).decode(TaxClassification.serializer())
    }

    // Stripe's own recorded tax figures for [fromDate, toDate) -- a
    // cross-check against build_tax_report's own figures for the same
    // range, only covering Stripe-processed payments. Best-effort on the
    // backend: an unconfigured Stripe account or any failure returns
    // zeros, never a 5xx.
    suspend fun getStripeReconcile(fromDate: String, toDate: String): ApiResult<StripeTaxReconcile> =
        with(plumbing) {
            val url = urlBuilder("/api/admin/tax/stripe-reconcile").apply {
                addQueryParameter("from_date", fromDate)
                addQueryParameter("to_date", toDate)
            }.build()
            request(method = "GET", url = url).decode(StripeTaxReconcile.serializer())
        }

    suspend fun listTaxRules(): ApiResult<List<TaxRule>> = with(plumbing) {
        request(method = "GET", path = "/api/admin/tax/rules").decode(ListSerializer(TaxRule.serializer()))
    }

    // Requires a government-source citation_url -- the backend rejects
    // anything else with a 400 (migration 0027_tax_rule_citation); the
    // caller's UI must validate this is non-blank before ever invoking
    // this method.
    suspend fun addTaxRule(input: TaxRuleCreateRequest): ApiResult<TaxRule> = with(plumbing) {
        val body = json.encodeToString(TaxRuleCreateRequest.serializer(), input).toRequestBody(JSON_MEDIA_TYPE)
        request(method = "POST", path = "/api/admin/tax/rules", body = body).decode(TaxRule.serializer())
    }

    // -- version ---------------------------------------------------------------

    suspend fun getVersionInfo(): ApiResult<VersionInfo> = with(plumbing) {
        request(method = "GET", path = "/api/admin/version").decode(VersionInfo.serializer())
    }
}
