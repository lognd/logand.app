from __future__ import annotations

import argparse
import asyncio
import mimetypes
import sys
from pathlib import Path

from logand_backend.app.config import AppConfig
from logand_backend.domain.storage.factory import get_storage_backend

# For PUBLIC-facing assets (project photos/videos/PDFs on the Projects
# page) -- deliberately separate from api/documents.py's upload route,
# which is admin-authenticated and meant for PRIVATE files (CAD/manuals/
# inventory docs an admin downloads while logged in). A marketing image
# needs to load on a public page with no session at all, so it needs a
# real public URL, which only StorageBackend.url() returning non-None
# provides -- in practice, R2 with R2_PUBLIC_BASE_URL configured (see
# docs/secrets.md). LocalFilesystemStorage's url() always returns None,
# so this script still uploads successfully against it (useful for
# testing) but warns loudly that nothing can actually reach the file.
#
# Cache-Control is set generously (1 year, immutable) -- these are
# project-showcase assets that essentially never change once uploaded;
# if a photo needs replacing, upload it under a NEW key (e.g. add a
# version suffix) rather than overwriting the old one, so browsers/CDN
# caches that already have the old URL cached don't need to be invalidated
# at all -- the old URL simply stops being referenced anywhere.
_CACHE_CONTROL = "public, max-age=31536000, immutable"


def upload_one(cfg: AppConfig, path: Path, key_prefix: str) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    key = f"{key_prefix.rstrip('/')}/{path.name}"
    backend = get_storage_backend(cfg)

    async def _do_upload() -> str | None:
        data = path.read_bytes()
        await backend.put(key, data, content_type, cache_control=_CACHE_CONTROL)
        return await backend.url(key)

    url = asyncio.run(_do_upload())
    if url is None:
        print(
            f"WARNING: uploaded {path.name} to key {key!r}, but this storage "
            "backend has no public URL (local backend, or R2 without "
            "R2_PUBLIC_BASE_URL set) -- nothing can actually reach this file "
            "from a public page yet. See docs/secrets.md's STORAGE_BACKEND "
            "section.",
            file=sys.stderr,
        )
        return f"(no public URL) key={key}"
    return url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload one or more local files to the configured public "
        "storage backend (see STORAGE_BACKEND in backend/.env) and print "
        "the resulting public URL for each -- for pasting into the Projects "
        "page's content, not for private admin documents (use the app's "
        "own admin UI for those)."
    )
    parser.add_argument(
        "files", nargs="+", type=Path, help="local file paths to upload"
    )
    parser.add_argument(
        "--prefix",
        default="projects",
        help="storage key prefix (default: 'projects', e.g. key becomes "
        "'<prefix>/<filename>')",
    )
    args = parser.parse_args()

    cfg = AppConfig.from_external(argparse.Namespace())
    for path in args.files:
        if not path.is_file():
            print(f"skipping {path}: not a file", file=sys.stderr)
            continue
        url = upload_one(cfg, path, args.prefix)
        print(f"{path.name} -> {url}")


if __name__ == "__main__":
    main()
