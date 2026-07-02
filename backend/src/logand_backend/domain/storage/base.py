from __future__ import annotations

from typing import Protocol

# The one interface every caller (budget evidence, receipts, documents/CAD
# files) is written against -- domain code never imports
# LocalFilesystemStorage or CloudflareR2Storage directly, only this
# Protocol, so swapping STORAGE_BACKEND (local -> R2 -> a future NAS
# backend) is a config change, not a code change, in any caller. Deliberately
# NOT an ABC -- a Protocol lets a future NAS backend (e.g. one that talks
# SFTP) satisfy this interface without importing/subclassing anything from
# this module, matching this codebase's typani-first, structural-typing
# leaning (see ~/.claude/refs/typani.md).
#
# `key` is always a caller-chosen, storage-backend-agnostic string path
# (e.g. "budget-evidence/{entry_id}/{filename}") -- never a full URL. Only
# `url()` translates a key into something a client can actually fetch, and
# for backends with no direct public URL (local filesystem, an R2 bucket
# with no public access configured) it returns None, and the caller must
# fall back to streaming bytes through the backend's own API instead.


class StorageBackend(Protocol):
    async def put(
        self,
        key: str,
        data: bytes,
        content_type: str,
        *,
        cache_control: str | None = None,
    ) -> None:
        """Writes `data` to `key`, creating or overwriting it. `cache_control`
        is a real HTTP Cache-Control value (e.g. "public, max-age=31536000,
        immutable") -- only meaningful for a backend whose `url()` returns a
        real public URL a browser fetches directly (R2); ignored by
        LocalFilesystemStorage, since nothing ever fetches a local-backend
        object directly (every caller proxies bytes through this app's own
        API, which sets its own response headers instead). Optional,
        defaulting to the backend's own default (no explicit header) --
        most callers (private evidence/receipt/document uploads) don't need
        long-lived public caching at all.
        """
        ...

    async def get(self, key: str) -> bytes:
        """Raises StorageObjectNotFound if `key` doesn't exist."""
        ...

    async def delete(self, key: str) -> None:
        """A no-op (not an error) if `key` doesn't exist -- matches
        idempotent-delete conventions elsewhere in this codebase."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def url(self, key: str) -> str | None:
        """A directly fetchable URL for `key`, or None if this backend has
        no such thing (the caller must proxy the bytes through its own API
        instead, e.g. a GET route that calls .get() and streams it back)."""
        ...


class StorageObjectNotFound(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"storage object not found: {key}")
        self.key = key
