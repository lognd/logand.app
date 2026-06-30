#!/bin/sh
# Nightly backup: pg_dump + budget-evidence tarball -> /backup staging volume.
# TODO(logan): push the staged files to off-box storage (object storage bucket or a
# second VPS) -- this script currently only stages locally, which is NOT a real backup
# per docs/design/11-deployment.md ("single VPS with no off-box backup is a single
# point of failure"). Wire up `rclone` or `aws s3 cp` here before relying on this.
set -eu

STAMP="$(date +%Y%m%d-%H%M%S)"
STAGING="/backup/${STAMP}"
mkdir -p "${STAGING}"

pg_dump "${DATABASE_URL}" | gzip > "${STAGING}/postgres.sql.gz"
tar -czf "${STAGING}/evidence.tar.gz" -C /evidence .

# Retention: 30 daily, 12 monthly -- see docs/design/11-deployment.md. Not yet implemented
# here; staging dir grows unbounded until off-box push + pruning is wired up.

echo "backup staged at ${STAGING}"
