"""Unit test for cli.py's `-k` keyword filter -- no network, no SSH, no
real production access (same self-test category as
test_revert_guarantee.py; see that file's own doc comment on why this
directory has a CI-eligible tests/ alongside the never-in-CI probes/).
"""

from __future__ import annotations

from scripts.prodtest.cli import select_probes
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe


class _NamedProbe(Probe):
    def __init__(self, name: str) -> None:
        self.name = name

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        pass


_PROBES = [
    _NamedProbe("notifications.invoice_and_payment_email_send"),
    _NamedProbe("notifications.refund_settled_email_send"),
    _NamedProbe("auth.wrong_password_rejected"),
    _NamedProbe("invoices.create_send_manual_payment"),
]


def test_no_keyword_selects_everything_and_skips_nothing() -> None:
    selected, skipped = select_probes(_PROBES, None)
    assert selected == _PROBES
    assert skipped == []


def test_keyword_matches_by_substring_case_insensitively() -> None:
    selected, skipped = select_probes(_PROBES, "NOTIFICATIONS")
    assert [p.name for p in selected] == [
        "notifications.invoice_and_payment_email_send",
        "notifications.refund_settled_email_send",
    ]
    assert [p.name for p in skipped] == [
        "auth.wrong_password_rejected",
        "invoices.create_send_manual_payment",
    ]


def test_keyword_matching_nothing_selects_nothing() -> None:
    selected, skipped = select_probes(_PROBES, "nonexistent-probe-name")
    assert selected == []
    assert skipped == _PROBES


def test_selected_plus_skipped_always_accounts_for_every_probe() -> None:
    # The CLI's summary line has to reflect every probe in ALL_PROBES
    # regardless of the filter -- a probe silently vanishing from the
    # report (neither run nor reported SKIP) would be worse than a
    # loud failure.
    for keyword in (None, "notifications", "auth", "nothing-matches"):
        selected, skipped = select_probes(_PROBES, keyword)
        assert len(selected) + len(skipped) == len(_PROBES)
        assert set(p.name for p in selected) | set(p.name for p in skipped) == {
            p.name for p in _PROBES
        }
