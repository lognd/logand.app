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


class SmtpReachabilityProbe(Probe):
    name = "notifications.smtp_reachable"
    description = (
        "SSH + health_check.py confirms SMTP_HOST:SMTP_PORT is configured "
        "and reachable (a raw TCP connect, per check_smtp()) and "
        "MAILING_ADDRESS is set (CAN-SPAM requires it once email is on). "
        "Does NOT authenticate or send a real message -- see "
        "notification_flow.py's InvoiceNotificationEmailProbe for the real "
        "end-to-end send-path check. Zero mutation."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        output = run_health_check(env)
        assert "smtp: not configured" not in output, (
            "SMTP_HOST is unset on the deployed backend -- expected it to "
            "be configured. Full report:\n" + output
        )
        assert "MAILING_ADDRESS is empty" not in output, (
            "MAILING_ADDRESS is unset -- CAN-SPAM requires a real postal "
            "address in every commercial email's footer. Full report:\n" + output
        )
        reachable_lines = [
            line
            for line in output.splitlines()
            if "smtp:" in line and "reachable" in line and "unreachable" not in line
        ]
        assert reachable_lines, (
            "expected a 'smtp: <host>:<port> reachable' line -- got:\n" + output
        )
