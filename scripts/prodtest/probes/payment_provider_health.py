from __future__ import annotations

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.health_check_runner import run_health_check
from scripts.prodtest.revert import Cleanup, Probe


class StripeLiveCredentialsProbe(Probe):
    name = "payment_providers.stripe_live_credentials"
    description = (
        "SSH + `python -m logand_backend.scripts.health_check` on the real "
        "backend container, confirms the report's Payment providers section "
        "shows Stripe credentials valid in LIVE mode (not test mode, not "
        "rejected). Zero mutation -- health_check.py's own Stripe check is "
        "a single read-only stripe.Balance.retrieve() call; nothing is "
        "created, captured, or charged."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        output = run_health_check(env)
        # Exact string health_check.py's check_stripe() logs on success --
        # see that function's own `mode = "live" if ... startswith
        # ("sk_live_") else "test"` line. Requiring "(live mode)"
        # specifically (not just "no FAIL for stripe") is deliberate: if
        # PAYMENT_PROCESSOR_SECRET were still unset/the dev-default fake
        # key, check_stripe() returns True without logging any FAIL line
        # at all (it defers that report to check_dev_defaults), which
        # would otherwise let this probe pass on a deployment that was
        # never actually configured for Stripe.
        assert "stripe: credentials valid (live mode)" in output, (
            "expected health_check.py to report "
            "'stripe: credentials valid (live mode)' -- got:\n" + output
        )


class PaypalLiveCredentialsProbe(Probe):
    name = "payment_providers.paypal_live_credentials"
    description = (
        "SSH + `python -m logand_backend.scripts.health_check` on the real "
        "backend container, confirms the report's Payment providers section "
        "shows PayPal credentials valid in LIVE mode (not sandbox, not "
        "rejected). Zero mutation -- health_check.py's own check_paypal() is "
        "a single read-only OAuth2 client-credentials token exchange "
        "(paypal._get_access_token); no order is created, captured, or "
        "charged. Mirrors StripeLiveCredentialsProbe: requiring '(live "
        "mode)' specifically (not just 'no FAIL for paypal') is deliberate "
        "-- check_paypal() returns True and logs no FAIL when PayPal is "
        "simply unconfigured, which would otherwise let this probe pass on "
        "a deployment that never had PayPal set up, and it also catches a "
        "deployment still left pointing at PAYPAL_MODE=sandbox."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        output = run_health_check(env)
        # Exact string health_check.py's check_paypal() logs on success --
        # see that function's `log.ok(f"paypal: credentials valid
        # ({cfg.paypal_mode} mode)")` line.
        assert "paypal: credentials valid (live mode)" in output, (
            "expected health_check.py to report "
            "'paypal: credentials valid (live mode)' -- got:\n" + output
        )


class SmtpReachabilityProbe(Probe):
    name = "notifications.smtp_reachable"
    description = (
        "SSH + health_check.py confirms a mail transport is configured and "
        "working -- either SMTP_HOST:SMTP_PORT reachable (a raw TCP "
        "connect, per check_smtp()'s SMTP branch) or, for a Google "
        "Workspace deployment, Gmail OAuth2 credentials actually valid (a "
        "real, read-only JWT-Bearer token exchange against Google's real "
        "oauth2 endpoint -- see check_smtp()'s Gmail branch and mailer.py's "
        "own doc comment on why Workspace can't use plain SMTP auth at all "
        "anymore, as of March 2025). Also confirms MAILING_ADDRESS is set "
        "(CAN-SPAM requires it once email is on). Does NOT send a real "
        "message -- see notification_flow.py's InvoiceNotificationEmailProbe "
        "for the real end-to-end send-path check. Zero mutation either way."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        output = run_health_check(env)
        assert "smtp: not configured" not in output, (
            "Neither SMTP_HOST nor GMAIL_SERVICE_ACCOUNT_JSON/"
            "GMAIL_SENDER_EMAIL is set on the deployed backend -- expected "
            "a mail transport to be configured. Full report:\n" + output
        )
        assert "MAILING_ADDRESS is empty" not in output, (
            "MAILING_ADDRESS is unset -- CAN-SPAM requires a real postal "
            "address in every commercial email's footer. Full report:\n" + output
        )
        smtp_reachable = any(
            "smtp:" in line and "reachable" in line and "unreachable" not in line
            for line in output.splitlines()
        )
        gmail_oauth_valid = "smtp: gmail oauth2 credentials valid" in output
        assert smtp_reachable or gmail_oauth_valid, (
            "expected either a 'smtp: <host>:<port> reachable' line or a "
            "'smtp: gmail oauth2 credentials valid' line -- got:\n" + output
        )
