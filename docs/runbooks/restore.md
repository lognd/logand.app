# Runbook: restoring from backup

Referenced from [design/11-deployment.md](../design/11-deployment.md)'s
backup section. See [deployment.md](../deployment.md)'s Backups
section and [secrets.md](../secrets.md)'s `BACKUP_R2_*` entry for how
backups actually get off the VPS.

## What gets backed up

- A full `pg_dump` of the Postgres database (`postgres.sql.gz`).
- A tarball of the storage volume (`storage.tar.gz`) -- every
  budget-evidence/receipt/document file, regardless of whether
  `STORAGE_BACKEND` is `local` or `r2` (the volume is backed up either
  way; if you're running `r2`, R2 itself is also already durable on its
  own, so this tarball is a secondary copy in that case, not the only one).

Staged nightly under `/backup/<timestamp>/` inside the `backup`
container's own volume, THEN pushed to the `BACKUP_R2_*` bucket (see
`ops/backup.sh`). Local staging only keeps the 3 most recent runs; the
real retention (30 backups) lives in R2.

## Restoring from R2 (the normal case -- VPS is gone or local staging expired)

1. Fetch the backup you want from R2 to the new/repaired host:
   ```bash
   rclone copy ":s3:<BACKUP_R2_BUCKET>/<timestamp>" ./restored-backup \
     --s3-provider=Cloudflare \
     --s3-access-key-id=<BACKUP_R2_ACCESS_KEY_ID> \
     --s3-secret-access-key=<BACKUP_R2_SECRET_ACCESS_KEY> \
     --s3-endpoint=<BACKUP_R2_ENDPOINT_URL>
   ```
   To see what's available first: same command with `rclone lsf
   ":s3:<BACKUP_R2_BUCKET>" --dirs-only` instead of `copy`.
2. Continue with "Restoring the database" and "Restoring storage
   files" below, using `./restored-backup/postgres.sql.gz` and
   `./restored-backup/storage.tar.gz` in place of the staged-locally
   paths those sections reference.

## Restoring from local staging (only if it's still there -- last 3 runs)

```bash
docker compose exec backup ls /backup   # lists available <timestamp> dirs
```

## Restoring the database

1. **Stop the backend first** -- don't restore into a database another
   process is actively writing to.
   ```bash
   docker compose stop backend
   ```
2. Drop and recreate the schema, then restore:
   ```bash
   docker compose exec postgres psql -U logand -d logand -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   gunzip -c postgres.sql.gz | docker compose exec -T postgres psql -U logand -d logand
   ```
   (If restoring from local staging instead of a fetched R2 copy:
   `docker compose exec backup sh -c "gunzip -c /backup/<timestamp>/postgres.sql.gz"`
   piped the same way.)
3. Bring the backend back up and confirm the data looks right:
   ```bash
   docker compose up -d backend
   curl -s https://yourdomain/api/me   # expect 401 (backend is answering), then spot-check real data via the admin UI
   ```

## Restoring storage files

The `backend` service mounts the `storage_data` volume at
`/app/data/storage` (see `docker-compose.yml`) -- restore into that
same volume, not a copy sitting outside it:

```bash
docker compose cp storage.tar.gz backend:/tmp/storage.tar.gz
docker compose exec backend sh -c "cd /app/data/storage && tar -xzf /tmp/storage.tar.gz && rm /tmp/storage.tar.gz"
```

If running `STORAGE_BACKEND=r2`, the real files already live in R2
independently of this tarball -- only restore this if R2 itself was
somehow also lost (i.e. you're restoring the backup bucket's own
contents back into the primary bucket), which is a different,
R2-to-R2 operation (`rclone copy` between the two, not this tarball
step).

## After any restore

- Re-check `alembic_version` matches what `alembic upgrade head` (run
  via `docker compose --profile migrate run --rm migrate`) expects --
  a backup taken before a migration was applied needs that migration
  re-run after restoring.
- Spot-check a few real records through the actual UI (an invoice, a
  budget entry, a mileage log) rather than trusting row counts alone.
- If this was a real incident (not a drill), write down what happened
  and when in whatever the operator's own incident log is -- this
  runbook doesn't prescribe one, but "we restored from backup" is worth
  recording somewhere durable.
