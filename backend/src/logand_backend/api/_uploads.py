from __future__ import annotations

from fastapi import HTTPException, Request, UploadFile

from logand_backend.logging import get_logger

_log = get_logger(__name__)

# 25MB: generous enough for a phone photo, a scanned PDF, or a small CAD
# file, small enough that a handful of concurrent uploads can't OOM or
# fill the disk of a single uvicorn worker. Shared by every UploadFile
# route so the cap can't drift between them -- see FINDINGS.md M1.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_CHUNK_SIZE = 1024 * 1024


async def read_upload_capped(
    file: UploadFile, request: Request | None = None, max_bytes: int = MAX_UPLOAD_BYTES
) -> bytes:
    """Read an UploadFile in fixed-size chunks, raising 413 the moment the
    total exceeds max_bytes instead of buffering an unbounded body into
    memory via a single `await file.read()`.

    By the time this runs, Starlette has already fully received the
    multipart body and spooled it into the UploadFile's own
    SpooledTemporaryFile (memory up to a small threshold, then disk) --
    the chunked read/raise loop below only bounds the *second* copy this
    function accumulates, it can't un-receive what was already spooled.
    Passing `request` lets us reject BEFORE that spooling finishes, using
    the client-supplied Content-Length header, so a body far over the cap
    is rejected without ever being fully read into the UploadFile. This is
    a courtesy fast-path only (a forged/absent Content-Length can't be
    trusted), not a substitute for a trusted front door -- see
    FINDINGS.md L1. The real backstop for a directly-exposed uvicorn
    worker (no proxy in front) is still the chunked loop below, which is
    why `request` remains optional rather than required.
    """
    detail = f"upload exceeds the {max_bytes // (1024 * 1024)}MB size limit"
    if request is not None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > max_bytes:
                _log.warning(
                    "upload rejected: declared content-length exceeds size cap",
                    extra={
                        "upload_filename": file.filename,
                        "max_bytes": max_bytes,
                        "declared_size": declared_size,
                    },
                )
                raise HTTPException(status_code=413, detail=detail)
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
                # "filename" collides with logging.LogRecord's own
                # reserved `filename` attribute (the source file the log
                # call was made from) -- passing it via `extra` raises
                # KeyError out of Logger.makeRecord itself, before any
                # handler/formatter runs, turning every real 413 into an
                # unhandled 500. Found while writing FINDINGS.md M1's
                # test coverage.
                extra={"upload_filename": file.filename, "max_bytes": max_bytes},
            )
            raise HTTPException(status_code=413, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)
