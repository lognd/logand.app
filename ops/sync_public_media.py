from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Uploads new/changed files under frontend/public/local-media/ to R2 via
# backend/src/logand_backend/scripts/upload_public_asset.py, tracked by a
# gitignored manifest (local-media/.uploaded_manifest.json) so unchanged
# files aren't re-uploaded on every push -- see ops/hooks/pre-push, which
# calls this script, and docs/secrets.md's STORAGE_BACKEND section for
# what backend/.env.local (this script's only credential source) needs.

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MEDIA_DIR = _REPO_ROOT / "frontend" / "public" / "local-media"
_MANIFEST_PATH = _MEDIA_DIR / ".uploaded_manifest.json"
_ENV_LOCAL = _REPO_ROOT / "backend" / ".env.local"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest() -> dict[str, str]:
    if not _MANIFEST_PATH.exists():
        return {}
    return json.loads(_MANIFEST_PATH.read_text())


def main() -> int:
    if not _MEDIA_DIR.exists():
        print(f"no {_MEDIA_DIR} directory, nothing to sync")
        return 0

    if not _ENV_LOCAL.exists():
        print(
            f"error: {_ENV_LOCAL} not found -- create it with R2_BUCKET, "
            "R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "STORAGE_BACKEND=r2 (see docs/secrets.md's STORAGE_BACKEND "
            "section). This file is gitignored and never deployed.",
            file=sys.stderr,
        )
        return 1

    manifest = _load_manifest()
    files = sorted(p for p in _MEDIA_DIR.iterdir() if p.is_file() and p != _MANIFEST_PATH)

    to_upload: list[Path] = []
    hashes: dict[str, str] = {}
    for path in files:
        digest = _sha256(path)
        hashes[path.name] = digest
        if manifest.get(path.name) != digest:
            to_upload.append(path)

    if not to_upload:
        print("sync_public_media: nothing changed, nothing to upload")
        return 0

    print(f"sync_public_media: uploading {len(to_upload)} new/changed file(s)")
    result = subprocess.run(
        [
            "uv",
            "run",
            "--env-file",
            str(_ENV_LOCAL),
            "python",
            "-m",
            "logand_backend.scripts.upload_public_asset",
            *[str(p) for p in to_upload],
            "--prefix",
            "projects",
        ],
        cwd=_REPO_ROOT / "backend",
    )
    if result.returncode != 0:
        print("sync_public_media: upload failed, manifest not updated", file=sys.stderr)
        return result.returncode

    for path in to_upload:
        manifest[path.name] = hashes[path.name]
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
