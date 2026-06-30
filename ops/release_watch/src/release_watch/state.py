from __future__ import annotations

from pathlib import Path

from typani.option import Nothing, Option, Some


def read_deployed_tag(state_path: Path) -> Option[str]:
    if not state_path.exists():
        return Nothing()
    return Some(state_path.read_text().strip())


def write_deployed_tag(state_path: Path, tag: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(tag)
