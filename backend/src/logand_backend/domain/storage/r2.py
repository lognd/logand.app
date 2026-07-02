from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from logand_backend.domain.storage.base import StorageObjectNotFound

# Cloudflare R2 is S3-API-compatible -- boto3's plain S3 client works
# against it unmodified, just pointed at R2's own endpoint_url with R2's
# own credentials, no Cloudflare-specific SDK needed. No egress fees (the
# actual reason to pick this over a "real" S3/GCS bucket once traffic
# volume matters) and 11-nines durability -- see docs/design/13 for the
# cost/durability comparison this was chosen from.


class CloudflareR2Storage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        public_base_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = public_base_url
        # signature_version="s3v4" -- R2 requires this explicitly; boto3's
        # own default doesn't always negotiate it correctly against a
        # non-AWS S3-compatible endpoint.
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="auto",
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put_sync, key, data, content_type)

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes:
        try:
            resp: dict[str, Any] = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise StorageObjectNotFound(key) from exc
            raise
        return resp["Body"].read()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey"):
                return False
            raise
        return True

    async def url(self, key: str) -> str | None:
        # Only returns a real URL if a public custom domain is configured
        # for the bucket (R2_PUBLIC_BASE_URL) -- an R2 bucket with no
        # public access has no directly fetchable URL at all, same as
        # LocalFilesystemStorage, and the caller must proxy bytes through
        # the backend's own API instead.
        if self._public_base_url is None:
            return None
        return f"{self._public_base_url.rstrip('/')}/{key}"
