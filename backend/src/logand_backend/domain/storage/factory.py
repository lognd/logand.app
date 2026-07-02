from __future__ import annotations

from logand_backend.app.config import AppConfig
from logand_backend.domain.storage.base import StorageBackend
from logand_backend.domain.storage.local import LocalFilesystemStorage
from logand_backend.domain.storage.r2 import CloudflareR2Storage

# The ONE place that knows about every concrete StorageBackend
# implementation -- every caller (api/budget.py, api/receipts.py,
# api/documents.py) calls get_storage_backend(cfg) and only ever touches
# the StorageBackend Protocol after that. Adding a NAS backend later means
# adding one more branch here, never touching a caller.


def get_storage_backend(cfg: AppConfig) -> StorageBackend:
    if cfg.storage_backend == "local":
        return LocalFilesystemStorage(cfg.storage_local_dir)
    if cfg.storage_backend == "r2":
        if not (
            cfg.r2_bucket
            and cfg.r2_endpoint_url
            and cfg.r2_access_key_id
            and cfg.r2_secret_access_key
        ):
            raise RuntimeError(
                "STORAGE_BACKEND=r2 requires R2_BUCKET, R2_ENDPOINT_URL, "
                "R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY to all be set"
            )
        return CloudflareR2Storage(
            bucket=cfg.r2_bucket,
            endpoint_url=cfg.r2_endpoint_url,
            access_key_id=cfg.r2_access_key_id,
            secret_access_key=cfg.r2_secret_access_key,
            public_base_url=cfg.r2_public_base_url,
        )
    raise RuntimeError(f"unknown STORAGE_BACKEND: {cfg.storage_backend!r}")
