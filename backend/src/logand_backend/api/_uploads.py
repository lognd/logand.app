from __future__ import annotations

from fastapi import HTTPException, UploadFile

from logand_backend.logging import get_logger

_log = get_logger(__name__)

# 25MB: generous enough for a phone photo, a scanned PDF, or a small CAD
# file, small enough that a handful of concurrent uploads can't OOM or
# fill the disk of a single uvicorn worker. Shared by every UploadFile
# route so the cap can't drift between them -- see FINDINGS.md M1.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_CHUNK_SIZE = 1024 * 1024


async def read_upload_capped(
    file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES
) -> bytes:
    """Read an UploadFile in fixed-size chunks, raising 413 the moment the
    total exceeds max_bytes instead of buffering an unbounded body into
    memory via a single `await file.read()`.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            _log.warning(
                "upload rejected: exceeds size cap",
                extra={"filename": file.filename, "max_bytes": max_bytes},
            )
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds the {max_bytes // (1024 * 1024)}MB size limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)
