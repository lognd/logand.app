"""The cleanup guarantee: every probe's mutations must be undone, even if
the probe raises partway through, and even if one revert action itself
fails (we still run the rest, and we still report the failure loudly --
a partially-cleaned-up production database is the single worst outcome
this harness can produce, worse than a false FAIL).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from scripts.prodtest.env import ProdEnv


@dataclass
class RevertAction:
    description: str
    fn: Callable[[], None]


@dataclass
class CleanupError:
    description: str
    error: str


class Cleanup:
    """A LIFO stack of revert actions. `defer()` right after each mutation
    (not batched at the end of `execute()`) -- if `execute()` raises on
    line 5 of 10, only the first 4 mutations' reverts should exist to run.
    """

    def __init__(self) -> None:
        self._actions: list[RevertAction] = []

    def defer(self, description: str, fn: Callable[[], None]) -> None:
        self._actions.append(RevertAction(description, fn))

    def close(self) -> list[CleanupError]:
        """Runs every deferred action in reverse order. Never stops early --
        one failed revert must not prevent the rest from at least being
        attempted. Returns the list of failures (empty == fully clean)."""
        errors: list[CleanupError] = []
        while self._actions:
            action = self._actions.pop()
            try:
                action.fn()
            except Exception as exc:  # noqa: BLE001 -- must keep going regardless
                errors.append(
                    CleanupError(action.description, f"{type(exc).__name__}: {exc}")
                )
        return errors

    @property
    def pending(self) -> list[str]:
        return [a.description for a in self._actions]


class Probe(ABC):
    """One black-box production test. Subclasses never talk to the DB
    directly to set up state -- only through the real HTTP API (the same
    surface a real user/admin has) plus SSH for out-of-band verification
    that no artifact was left behind. Every mutating call must be paired
    with a `cleanup.defer(...)` in the same statement group, before the
    next mutating call runs.
    """

    name: str
    description: str = ""

    @abstractmethod
    def check_capability(self, env: "ProdEnv") -> bool | str:
        """Return True if this probe can run against `env` right now, or a
        human-readable skip reason (e.g. a feature the server doesn't have
        configured, like PayPal or R2 storage) as a string."""

    @abstractmethod
    def execute(self, env: "ProdEnv", cleanup: Cleanup) -> None:
        """Run the real test. Raise (AssertionError or otherwise) on any
        unexpected response/state -- that's a FAIL. Must call
        `cleanup.defer(...)` for every mutation as soon as it's made."""
