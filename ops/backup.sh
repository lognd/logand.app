#!/bin/sh
# Nightly backup: pg_dump + storage-volume tarball -> /backup staging,
# then pushed off-box to R2 via rclone (an on-the-fly S3-compatible
# remote, no rclone.conf needed -- see BACKUP_R2_* below). A single-VPS
# deployment with only on-box backups is a single point of failure (the
# VPS itself dying takes the backups with it) -- see
# docs/design/11-deployment.md.
set -eu

STAMP="$(date +%Y%m%d-%H%M%S)"
STAGING="/backup/${STAMP}"
mkdir -p "${STAGING}"

# DATABASE_URL is the app's own SQLAlchemy/asyncpg URL
# ("postgresql+asyncpg://...") -- pg_dump's libpq connection parser
# doesn't recognize the "+asyncpg" driver suffix at all and silently
# falls back to a local-socket connection instead of erroring loudly on
# the unrecognized scheme, so this would have failed on every real run
# without ever actually producing a database dump. Confirmed against a
# real Postgres: "postgresql+asyncpg://..." fails to connect,
# "postgresql://..." (the same URL with the suffix stripped) works.
PG_DUMP_URL=$(echo "${DATABASE_URL}" | sed 's/^postgresql+asyncpg:/postgresql:/')
pg_dump "${PG_DUMP_URL}" | gzip > "${STAGING}/postgres.sql.gz"
tar -czf "${STAGING}/storage.tar.gz" -C /evidence .

echo "backup staged at ${STAGING}"

# BACKUP_R2_* are deliberately separate from the app's own R2_* (used by
# STORAGE_BACKEND=r2, see domain/storage/r2.py) -- a bug in one shouldn't
# be able to corrupt or leak into the other, and a deployment running
# STORAGE_BACKEND=local still needs a real off-box destination for THIS
# script regardless of what (if anything) the app itself uses R2 for.
if [ -z "${BACKUP_R2_BUCKET:-}" ] || [ -z "${BACKUP_R2_ENDPOINT_URL:-}" ] \
    || [ -z "${BACKUP_R2_ACCESS_KEY_ID:-}" ] || [ -z "${BACKUP_R2_SECRET_ACCESS_KEY:-}" ]; then
    echo "WARNING: BACKUP_R2_* not fully configured -- backup staged locally" \
         "at ${STAGING} but NOT pushed off-box. A VPS-level failure would" \
         "lose this backup along with everything else. See" \
         "docs/secrets.md's BACKUP_R2_* section." >&2
    exit 0
fi

rclone copy "${STAGING}" ":s3:${BACKUP_R2_BUCKET}/${STAMP}" \
    --s3-provider=Cloudflare \
    --s3-access-key-id="${BACKUP_R2_ACCESS_KEY_ID}" \
    --s3-secret-access-key="${BACKUP_R2_SECRET_ACCESS_KEY}" \
    --s3-endpoint="${BACKUP_R2_ENDPOINT_URL}" \
    --s3-no-check-bucket

echo "backup pushed to r2://${BACKUP_R2_BUCKET}/${STAMP}"

# Retention: keep the 30 most recent off-box backups, prune older ones --
# runs AFTER a successful push, so a failed/interrupted push never
# deletes an older-but-still-good backup before a replacement exists.
# Local staging (this container's own /backup volume) is pruned to just
# the most recent 3 runs -- it only ever needs to cover "the push
# script itself was broken for a few days," not serve as the real
# retention store (R2 is).
REMOTE_BACKUPS=$(rclone lsf ":s3:${BACKUP_R2_BUCKET}" \
    --s3-provider=Cloudflare \
    --s3-access-key-id="${BACKUP_R2_ACCESS_KEY_ID}" \
    --s3-secret-access-key="${BACKUP_R2_SECRET_ACCESS_KEY}" \
    --s3-endpoint="${BACKUP_R2_ENDPOINT_URL}" \
    --dirs-only | sort)
TOTAL=$(printf '%s\n' "${REMOTE_BACKUPS}" | grep -c . || true)
KEEP=30
if [ "${TOTAL}" -gt "${KEEP}" ]; then
    PRUNE_COUNT=$((TOTAL - KEEP))
    printf '%s\n' "${REMOTE_BACKUPS}" | head -n "${PRUNE_COUNT}" | while read -r old; do
        [ -z "${old}" ] && continue
        rclone purge ":s3:${BACKUP_R2_BUCKET}/${old}" \
            --s3-provider=Cloudflare \
            --s3-access-key-id="${BACKUP_R2_ACCESS_KEY_ID}" \
            --s3-secret-access-key="${BACKUP_R2_SECRET_ACCESS_KEY}" \
            --s3-endpoint="${BACKUP_R2_ENDPOINT_URL}"
        echo "pruned old backup r2://${BACKUP_R2_BUCKET}/${old}"
    done
fi

find /backup -maxdepth 1 -mindepth 1 -type d | sort | head -n -3 | xargs -r rm -rf
