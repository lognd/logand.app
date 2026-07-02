from __future__ import annotations

import asyncio
from pathlib import Path

from logand_backend.domain.storage.base import StorageObjectNotFound

# Default backend -- zero-cost, zero-external-dependency (no R2/cloud
# account required to run this app at all), the right choice up to
# "medium" scale on a single host. Deliberately has no `url()` support
# (always returns None) -- files here aren't reachable by any public URL,
# only by the backend proxying bytes through its own authenticated API
# routes, which is also strictly safer (no accidental public bucket).


class LocalFilesystemStorage:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _resolve(self, key: str) -> Path:
        # `key` may contain "/" as a caller-chosen namespace separator
        # (e.g. "budget-evidence/{entry_id}/{filename}") -- resolve
        # against base_dir and reject anything that would escape it
        # (a filename containing "..", say) rather than trusting caller
        # input to already be a safe relative path.
        path = (self._base_dir / key).resolve()
        if (
            self._base_dir.resolve() not in path.parents
            and path != self._base_dir.resolve()
        ):
            raise ValueError(f"storage key escapes base_dir: {key!r}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type  # unused -- local files have no separate content-type slot
        path = self._resolve(key)
        await asyncio.to_thread(self._write_sync, path, data)

    def _write_sync(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise StorageObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return await asyncio.to_thread(path.exists)

    async def url(self, key: str) -> str | None:
        del key
        return None
