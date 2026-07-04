from scripts.prodtest.probes.admin_customer_management import (
    AdminCustomerManagementProbe,
)
from scripts.prodtest.probes.auth_flow import (
    AdminLoginCsrfLogoutProbe,
    CustomerRegisterLoginLogoutProbe,
    SessionKillAllProbe,
    WrongPasswordRejectedProbe,
)
from scripts.prodtest.probes.budget_flow import BudgetEntryLifecycleProbe
from scripts.prodtest.probes.document_flow import DocumentUploadDeleteProbe
from scripts.prodtest.probes.health import HealthCheckProbe
from scripts.prodtest.probes.inventory_flow import InventoryItemLifecycleProbe
from scripts.prodtest.probes.invoice_flow import InvoiceLifecycleProbe
from scripts.prodtest.probes.notification_flow import (
    InvoiceNotificationEmailProbe,
    RefundSettlementNotificationProbe,
)
from scripts.prodtest.probes.payment_provider_health import (
    SmtpReachabilityProbe,
    StripeLiveCredentialsProbe,
)
from scripts.prodtest.probes.receipt_flow import ReceiptUploadDeleteProbe

ALL_PROBES = [
    HealthCheckProbe(),
    WrongPasswordRejectedProbe(),
    AdminLoginCsrfLogoutProbe(),
    CustomerRegisterLoginLogoutProbe(),
    SessionKillAllProbe(),
    AdminCustomerManagementProbe(),
    InvoiceLifecycleProbe(),
    BudgetEntryLifecycleProbe(),
    InventoryItemLifecycleProbe(),
    DocumentUploadDeleteProbe(),
    ReceiptUploadDeleteProbe(),
    StripeLiveCredentialsProbe(),
    SmtpReachabilityProbe(),
    InvoiceNotificationEmailProbe(),
    RefundSettlementNotificationProbe(),
]
