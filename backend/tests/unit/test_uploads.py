from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from logand_backend.api._uploads import read_upload_capped

# FINDINGS.md M1: the 413 size-cap branch (and its "still succeeds at/under
# the cap" counterpart) had zero test coverage. Exercised directly against
# read_upload_capped with a small explicit max_bytes so the test stays fast
# -- no need to build a real 25MB payload to prove the off-by-one and
# raise/succeed branches are correct.


def _upload(data: bytes, filename: str = "f.bin") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=filename)


async def test_read_upload_capped_raises_413_over_the_cap() -> None:
    data = b"x" * 11
    with pytest.raises(HTTPException) as exc_info:
        await read_upload_capped(_upload(data), max_bytes=10)
    assert exc_info.value.status_code == 413
    assert "size limit" in exc_info.value.detail


async def test_read_upload_capped_succeeds_at_the_boundary() -> None:
    data = b"x" * 10
    contents = await read_upload_capped(_upload(data), max_bytes=10)
    assert contents == data


async def test_read_upload_capped_succeeds_under_the_cap() -> None:
    data = b"x" * 5
    contents = await read_upload_capped(_upload(data), max_bytes=10)
    assert contents == data


async def test_read_upload_capped_raises_413_across_multiple_chunks() -> None:
    """total accumulates across successive `file.read(_CHUNK_SIZE)` calls --
    prove the cap is enforced on the running total, not just a single read,
    by using a payload larger than the internal chunk size."""
    from logand_backend.api import _uploads

    data = b"y" * (_uploads._CHUNK_SIZE + 100)
    with pytest.raises(HTTPException) as exc_info:
        await read_upload_capped(_upload(data), max_bytes=_uploads._CHUNK_SIZE + 50)
    assert exc_info.value.status_code == 413
