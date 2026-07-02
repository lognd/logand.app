from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logand_backend.app.config import AppConfig
from logand_backend.domain.storage.base import StorageObjectNotFound
from logand_backend.domain.storage.factory import get_storage_backend
from logand_backend.domain.storage.local import LocalFilesystemStorage
from logand_backend.domain.storage.r2 import CloudflareR2Storage

# LocalFilesystemStorage: real filesystem I/O against a pytest tmp_path,
# not a mocked Path -- exactly the "real infra over mocks" convention used
# throughout this codebase's other testing doubles.


async def test_local_put_get_roundtrip(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    await storage.put("a/b/c.txt", b"hello world", "text/plain")
    assert await storage.get("a/b/c.txt") == b"hello world"
    assert await storage.exists("a/b/c.txt") is True


async def test_local_get_missing_raises_not_found(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    with pytest.raises(StorageObjectNotFound):
        await storage.get("nope.txt")


async def test_local_exists_false_for_missing_key(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    assert await storage.exists("nope.txt") is False


async def test_local_delete_is_idempotent(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    await storage.delete("never-existed.txt")  # must not raise
    await storage.put("x.txt", b"data", "text/plain")
    await storage.delete("x.txt")
    await storage.delete("x.txt")  # second delete, still must not raise
    assert await storage.exists("x.txt") is False


async def test_local_url_is_always_none(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    await storage.put("x.txt", b"data", "text/plain")
    assert await storage.url("x.txt") is None


def test_local_rejects_key_that_escapes_base_dir(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    with pytest.raises(ValueError):
        storage._resolve("../../etc/passwd")


# CloudflareR2Storage: exercised against moto's real in-process S3 API
# double (same real-protocol-double convention as fake_stripe.py/
# fake_paypal.py/fake_smtp.py) -- boto3's actual HTTP client runs against
# it, not a monkeypatched method.


@pytest.fixture
def r2_storage():
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="x",
            aws_secret_access_key="x",
        )
        client.create_bucket(Bucket="test-bucket")
        yield CloudflareR2Storage(
            bucket="test-bucket",
            endpoint_url="https://s3.amazonaws.com",
            access_key_id="x",
            secret_access_key="x",
            public_base_url="https://files.example.com",
        )


async def test_r2_put_get_roundtrip(r2_storage: CloudflareR2Storage) -> None:
    await r2_storage.put("receipts/1.jpg", b"jpeg-bytes", "image/jpeg")
    assert await r2_storage.get("receipts/1.jpg") == b"jpeg-bytes"
    assert await r2_storage.exists("receipts/1.jpg") is True


async def test_r2_put_sets_cache_control_when_given(
    r2_storage: CloudflareR2Storage,
) -> None:
    await r2_storage.put(
        "projects/photo.jpg",
        b"jpeg-bytes",
        "image/jpeg",
        cache_control="public, max-age=31536000, immutable",
    )
    head = r2_storage._client.head_object(
        Bucket="test-bucket", Key="projects/photo.jpg"
    )
    assert head["CacheControl"] == "public, max-age=31536000, immutable"


async def test_r2_put_omits_cache_control_when_not_given(
    r2_storage: CloudflareR2Storage,
) -> None:
    await r2_storage.put("projects/photo2.jpg", b"jpeg-bytes", "image/jpeg")
    head = r2_storage._client.head_object(
        Bucket="test-bucket", Key="projects/photo2.jpg"
    )
    assert "CacheControl" not in head


async def test_local_put_accepts_and_ignores_cache_control(tmp_path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    await storage.put("x.txt", b"data", "text/plain", cache_control="public, max-age=1")
    assert await storage.get("x.txt") == b"data"


async def test_r2_get_missing_raises_not_found(r2_storage: CloudflareR2Storage) -> None:
    with pytest.raises(StorageObjectNotFound):
        await r2_storage.get("nope.jpg")


async def test_r2_exists_false_for_missing_key(r2_storage: CloudflareR2Storage) -> None:
    assert await r2_storage.exists("nope.jpg") is False


async def test_r2_delete_removes_object(r2_storage: CloudflareR2Storage) -> None:
    await r2_storage.put("x.txt", b"data", "text/plain")
    await r2_storage.delete("x.txt")
    assert await r2_storage.exists("x.txt") is False


async def test_r2_url_uses_public_base_url(r2_storage: CloudflareR2Storage) -> None:
    assert await r2_storage.url("a/b.jpg") == "https://files.example.com/a/b.jpg"


async def test_r2_url_none_without_public_base_url() -> None:
    with mock_aws():
        storage = CloudflareR2Storage(
            bucket="b",
            endpoint_url="https://s3.amazonaws.com",
            access_key_id="x",
            secret_access_key="x",
        )
        assert await storage.url("a.jpg") is None


# get_storage_backend factory


def test_factory_returns_local_by_default() -> None:
    cfg = AppConfig()
    backend = get_storage_backend(cfg)
    assert isinstance(backend, LocalFilesystemStorage)


def test_factory_returns_r2_when_configured() -> None:
    cfg = AppConfig(
        storage_backend="r2",
        r2_bucket="b",
        r2_endpoint_url="https://example.com",
        r2_access_key_id="x",
        r2_secret_access_key="x",
    )
    backend = get_storage_backend(cfg)
    assert isinstance(backend, CloudflareR2Storage)


def test_factory_raises_when_r2_selected_but_not_configured() -> None:
    cfg = AppConfig(storage_backend="r2")
    with pytest.raises(RuntimeError):
        get_storage_backend(cfg)


def test_factory_raises_on_unknown_backend() -> None:
    cfg = AppConfig(storage_backend="dropbox")
    with pytest.raises(RuntimeError):
        get_storage_backend(cfg)
