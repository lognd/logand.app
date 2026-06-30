from __future__ import annotations

from pathlib import Path

from release_watch.state import read_deployed_tag, write_deployed_tag


def test_read_missing_state_is_nothing(tmp_path: Path) -> None:
    result = read_deployed_tag(tmp_path / "deployed_version")
    assert result.is_nothing


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    state_path = tmp_path / "nested" / "deployed_version"
    write_deployed_tag(state_path, "v1.2.3")
    result = read_deployed_tag(state_path)
    assert result.is_some
    assert result.danger_some == "v1.2.3"
