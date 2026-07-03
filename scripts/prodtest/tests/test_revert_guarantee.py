"""Unit tests for the harness's own cleanup guarantee (revert.py) -- no
network, no SSH, no real production access. This IS the part of
scripts/prodtest that runs in CI (see ci.yml's prodtest-self-test job);
the actual probes in probes/ never do, by design (see cli.py's own
module docstring and this directory's README note).

These tests exist because the single most important property of the
whole harness -- "a probe that mutates production always gets reverted,
even when it raises, even when one revert itself fails" -- is exactly
the kind of thing that's easy to silently break in a refactor and easy
to verify precisely with plain function calls, no infrastructure needed.
"""

from __future__ import annotations

import pytest

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe
from scripts.prodtest.runner import FAIL, PASS, SKIP, run_probe


def _fake_env() -> ProdEnv:
    return ProdEnv(
        base_url="https://example.invalid",
        ssh_host_alias="nonexistent-host",
        admin_email="admin@example.invalid",
        admin_password="unused",
        backend_container="backend",
        postgres_container="postgres",
        db_user="user",
        db_name="db",
        storage_local_dir="/app/data/storage",
        notification_email="prodtest@example.invalid",
    )


class _RecordingProbe(Probe):
    """A probe whose execute() body is fully caller-controlled, so tests
    can drive exactly the sequences the real revert guarantee has to
    survive (mid-execute exceptions, failing reverts, etc)."""

    name = "test.recording"

    def __init__(self, body, capability: bool | str = True) -> None:
        self._body = body
        self._capability = capability

    def check_capability(self, env: ProdEnv) -> bool | str:
        return self._capability

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        self._body(env, cleanup)


def test_cleanup_runs_deferred_actions_in_reverse_order() -> None:
    order: list[str] = []
    cleanup = Cleanup()
    cleanup.defer("first", lambda: order.append("first"))
    cleanup.defer("second", lambda: order.append("second"))
    cleanup.defer("third", lambda: order.append("third"))

    errors = cleanup.close()

    assert errors == []
    assert order == ["third", "second", "first"]


def test_cleanup_runs_every_action_even_if_one_raises() -> None:
    order: list[str] = []
    cleanup = Cleanup()
    cleanup.defer("first", lambda: order.append("first"))

    def _boom() -> None:
        raise RuntimeError("revert exploded")

    cleanup.defer("second (fails)", _boom)
    cleanup.defer("third", lambda: order.append("third"))

    errors = cleanup.close()

    # "third" and "first" still ran despite "second" raising in between --
    # a mid-stack failure must never stop the rest of the reverts.
    assert order == ["third", "first"]
    assert len(errors) == 1
    assert errors[0].description == "second (fails)"
    assert "revert exploded" in errors[0].error


def test_cleanup_close_is_idempotent_when_nothing_pending() -> None:
    cleanup = Cleanup()
    assert cleanup.close() == []
    assert cleanup.close() == []  # calling again must not error or re-run anything


def test_partial_mutation_only_reverts_what_actually_ran() -> None:
    """The core guarantee this whole harness depends on: if execute()
    mutates twice, defers a revert after each mutation, then raises
    before a third mutation/defer, only the first two reverts should
    exist and run -- never a revert for a mutation that never happened.
    """
    order: list[str] = []

    def body(env: ProdEnv, cleanup: Cleanup) -> None:
        order.append("mutate-1")
        cleanup.defer("revert-1", lambda: order.append("revert-1"))
        order.append("mutate-2")
        cleanup.defer("revert-2", lambda: order.append("revert-2"))
        raise RuntimeError("simulated failure between mutation 2 and 3")

    outcome = run_probe(_RecordingProbe(body), _fake_env())

    assert outcome.status == FAIL
    assert "simulated failure" in outcome.detail
    assert order == ["mutate-1", "mutate-2", "revert-2", "revert-1"]


def test_run_probe_reports_pass_when_execute_succeeds_and_cleanup_is_clean() -> None:
    def body(env: ProdEnv, cleanup: Cleanup) -> None:
        cleanup.defer("noop", lambda: None)

    outcome = run_probe(_RecordingProbe(body), _fake_env())

    assert outcome.status == PASS
    assert outcome.detail == ""


def test_run_probe_fails_loudly_when_cleanup_fails_even_if_execute_passed() -> None:
    """The scenario this harness is most paranoid about: the test's own
    assertions all passed, but a revert failed -- meaning a real
    artifact may still be sitting on production. That MUST be reported
    as a failure, never silently folded into a passing result.
    """

    def body(env: ProdEnv, cleanup: Cleanup) -> None:
        def _broken_revert() -> None:
            raise RuntimeError("could not delete the row")

        cleanup.defer("delete row", _broken_revert)

    outcome = run_probe(_RecordingProbe(body), _fake_env())

    assert outcome.status == FAIL
    assert "CLEANUP FAILED" in outcome.detail
    assert "delete row" in outcome.detail
    assert "could not delete the row" in outcome.detail


def test_run_probe_skips_cleanly_when_capability_is_absent() -> None:
    def body(env: ProdEnv, cleanup: Cleanup) -> None:
        raise AssertionError("execute() must never run when capability check fails")

    outcome = run_probe(
        _RecordingProbe(body, capability="feature not configured on this server"),
        _fake_env(),
    )

    assert outcome.status == SKIP
    assert outcome.detail == "feature not configured on this server"


def test_run_probe_fails_when_check_capability_itself_raises() -> None:
    class _BrokenCapabilityProbe(Probe):
        name = "test.broken_capability"

        def check_capability(self, env: ProdEnv) -> bool | str:
            raise RuntimeError("network error probing capability")

        def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
            raise AssertionError("must never reach execute()")

    outcome = run_probe(_BrokenCapabilityProbe(), _fake_env())

    assert outcome.status == FAIL
    assert "network error probing capability" in outcome.detail


def test_psql_delete_row_rejects_unsafe_table_identifier() -> None:
    from scripts.prodtest.ssh_client import VpsSsh

    ssh = VpsSsh("unused-host-never-connected-to")
    with pytest.raises(ValueError, match="unsafe identifier"):
        ssh.psql_delete_row(
            container="c",
            db_user="u",
            db_name="d",
            table="users; DROP TABLE users",
            id_column="id",
            row_id="x",
        )
